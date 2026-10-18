"""Agentic weekly pipeline report.

Numbers come from SQL, never from the LLM. The analyst agent only receives the computed
metrics and writes the narrative + next actions, so it cannot hallucinate a figure.
"""

import json
import logging
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone

from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.llm import structured
from app.models import Lead, LeadStatus, Report
from app.notify import post_slack
from app.schemas import ReportNarrative

log = logging.getLogger(__name__)

ANALYST_SYSTEM = """You are a revenue operations analyst. You receive this week's lead pipeline metrics as JSON.
Write a short report for a solo consultant. Use ONLY numbers present in the JSON; never estimate or invent.
Give exactly three concrete actions for next week, each tied to a metric."""


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_metrics(s: Session, start: datetime, end: datetime) -> dict:
    leads = s.scalars(select(Lead).where(Lead.created_at >= start, Lead.created_at < end)).all()
    prev_total = s.scalar(
        select(func.count(Lead.id)).where(Lead.created_at >= start - (end - start), Lead.created_at < start)
    ) or 0

    status = Counter(lead.status for lead in leads)
    tiers = Counter(lead.tier for lead in leads if lead.tier)
    sources = Counter(lead.source for lead in leads)
    use_cases = Counter((lead.qualification or {}).get("use_case", "Unclear") for lead in leads
                        if lead.tier and lead.tier != "spam")
    scores = [lead.score for lead in leads if lead.score is not None and lead.tier != "spam"]
    review_hours = [
        (_aware(lead.reviewed_at) - _aware(lead.created_at)).total_seconds() / 3600
        for lead in leads if lead.reviewed_at
    ]
    decided = status[LeadStatus.SYNCED] + status[LeadStatus.REJECTED]

    pending_hot = s.scalars(
        select(Lead).where(Lead.status == LeadStatus.PENDING_APPROVAL, Lead.tier == "hot")
        .order_by(Lead.score.desc()).limit(5)
    ).all()

    total = len(leads)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "total_leads": total,
        "previous_period_total": prev_total,
        "wow_change_pct": round((total - prev_total) / prev_total * 100, 1) if prev_total else None,
        "by_status": dict(status),
        "by_tier": dict(tiers),
        "by_source": dict(sources.most_common()),
        "top_use_cases": dict(use_cases.most_common(5)),
        "avg_score": round(statistics.mean(scores), 1) if scores else None,
        "spam_filtered": status[LeadStatus.AUTO_REJECTED],
        "synced_to_crm": status[LeadStatus.SYNCED],
        "approval_rate_pct": round(status[LeadStatus.SYNCED] / decided * 100, 1) if decided else None,
        "median_hours_to_review": round(statistics.median(review_hours), 1) if review_hours else None,
        "awaiting_review": status[LeadStatus.PENDING_APPROVAL],
        "hot_leads_waiting": [
            {"id": lead.id, "company": lead.company or lead.email, "score": lead.score,
             "use_case": (lead.qualification or {}).get("use_case")}
            for lead in pending_hot
        ],
        "failed": status[LeadStatus.FAILED],
    }


def narrate_template(m: dict) -> ReportNarrative:
    tiers = m["by_tier"]
    wow = f" ({m['wow_change_pct']:+g}% vs previous week)" if m["wow_change_pct"] is not None else ""
    summary = (
        f"{m['total_leads']} inbound leads this week{wow}: {tiers.get('hot', 0)} hot, {tiers.get('warm', 0)} warm, "
        f"{tiers.get('cold', 0)} cold, {m['spam_filtered']} spam filtered automatically. "
        f"{m['synced_to_crm']} were approved and pushed to the CRM; {m['awaiting_review']} still await review."
    )
    if m["top_use_cases"]:
        top = next(iter(m["top_use_cases"]))
        summary += f" Most requested: {top}."
    risks, actions = [], []
    if m["hot_leads_waiting"]:
        risks.append(f"{len(m['hot_leads_waiting'])} hot lead(s) not reviewed yet: response time is the #1 close-rate driver.")
        actions.append("Review and reply to every hot lead in the approval queue today.")
    if m["median_hours_to_review"] and m["median_hours_to_review"] > 24:
        risks.append(f"Median review time is {m['median_hours_to_review']}h.")
        actions.append("Block two 15-minute review slots per day to bring review time under 24h.")
    if m["top_use_cases"]:
        actions.append(f"Publish a case study on '{next(iter(m['top_use_cases']))}', the most requested service.")
    if m["by_source"]:
        best = next(iter(m["by_source"]))
        actions.append(f"Double down on '{best}', the top lead source this week.")
    if m["failed"]:
        risks.append(f"{m['failed']} lead(s) failed processing; check the error log.")
    actions = (actions + ["Follow up with every warm lead that has not answered in 3 days."])[:3]
    headline = f"{m['total_leads']} leads, {tiers.get('hot', 0)} hot, {m['synced_to_crm']} in CRM"
    return ReportNarrative(headline=headline, summary=summary, risks=risks, actions=actions)


def narrate(m: dict, llm: BaseChatModel | None) -> tuple[ReportNarrative, str]:
    if llm is not None:
        try:
            chain = structured(llm, ReportNarrative)
            out = chain.invoke([("system", ANALYST_SYSTEM), ("human", json.dumps(m, default=str))])
            return out, "llm"
        except Exception as exc:
            log.warning("analyst LLM failed, using template: %s", exc)
    return narrate_template(m), "template"


def generate_report(session_factory: sessionmaker[Session], llm: BaseChatModel | None, *,
                    end: datetime | None = None, days: int = 7, slack_webhook_url: str = "") -> Report:
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    with session_factory() as s:
        metrics = compute_metrics(s, start, end)
        narrative, mode = narrate(metrics, llm)
        report = Report(period_start=start, period_end=end, metrics=metrics,
                        narrative=narrative.model_dump() | {"mode": mode})
        s.add(report)
        s.commit()
        s.refresh(report)
    if slack_webhook_url:
        n = report.narrative
        post_slack(slack_webhook_url, f"*Weekly pipeline: {n['headline']}*\n{n['summary']}\n"
                   + "\n".join(f"• {a}" for a in n["actions"]))
    return report
