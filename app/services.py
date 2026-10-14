"""Pipeline execution, the job queue and the human approval step."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.crm import CRMAdapter, CrmContact, CrmError
from app.models import Lead, LeadEvent, LeadStatus
from app.notify import post_slack
from app.schemas import ApproveIn, RejectIn

log = logging.getLogger(__name__)


def log_event(s: Session, lead_id: int, kind: str, detail: dict | None = None) -> None:
    s.add(LeadEvent(lead_id=lead_id, kind=kind, detail=detail or {}))


def lead_input(lead: Lead) -> dict:
    return {
        "email": lead.email, "first_name": lead.first_name, "last_name": lead.last_name, "company": lead.company,
        "website": lead.website, "phone": lead.phone, "job_title": lead.job_title, "message": lead.message,
        "source": lead.source,
    }


def claim(s: Session, lead_id: int) -> bool:
    """Atomic claim: only one worker can flip received -> processing, on Postgres and SQLite alike."""
    res = s.execute(
        update(Lead)
        .where(Lead.id == lead_id, Lead.status == LeadStatus.RECEIVED)
        .values(status=LeadStatus.PROCESSING, attempts=Lead.attempts + 1)
    )
    s.commit()
    return res.rowcount == 1


def process_lead(lead_id: int, session_factory: sessionmaker[Session], graph, settings: Settings) -> str | None:
    with session_factory() as s:
        if not claim(s, lead_id):
            return None
        lead = s.get(Lead, lead_id)
        try:
            result = graph.invoke({"lead": lead_input(lead), "warnings": [], "trace": []})
        except Exception as exc:
            log.exception("pipeline failed for lead %s", lead_id)
            lead.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            lead.status = LeadStatus.FAILED if lead.attempts >= settings.max_attempts else LeadStatus.RECEIVED
            log_event(s, lead.id, "pipeline_error", {"error": lead.last_error, "attempt": lead.attempts})
            s.commit()
            return lead.status

        lead.enrichment = result.get("enrichment")
        lead.qualification = result.get("qualification")
        lead.score = result.get("score")
        lead.score_breakdown = result.get("score_breakdown")
        lead.tier = result.get("tier")
        lead.crm_draft = result.get("crm_draft")
        lead.warnings = result.get("warnings") or None
        lead.status = result["status"]
        lead.last_error = None
        if not lead.company and lead.enrichment:
            lead.company = lead.enrichment.get("company_guess")
        for step in result.get("trace", []):
            log_event(s, lead.id, f"agent.{step['step']}", step)
        s.commit()

        if lead.tier == "hot" and settings.slack_webhook_url:
            q = lead.qualification or {}
            post_slack(settings.slack_webhook_url,
                       f":fire: Hot lead {lead.score}/100: {lead.company or lead.email} | {q.get('use_case')} | "
                       f"{q.get('need_summary')} | waiting for approval")
        return lead.status


def process_pending(session_factory: sessionmaker[Session], graph, settings: Settings, limit: int = 20) -> int:
    with session_factory() as s:
        ids = s.scalars(
            select(Lead.id).where(Lead.status == LeadStatus.RECEIVED, Lead.attempts < settings.max_attempts)
            .order_by(Lead.id).limit(limit)
        ).all()
    done = 0
    for lead_id in ids:
        if process_lead(lead_id, session_factory, graph, settings):
            done += 1
    return done


class InvalidState(Exception):
    pass


def approve_lead(s: Session, lead: Lead, data: ApproveIn, crm: CRMAdapter) -> Lead:
    if lead.status != LeadStatus.PENDING_APPROVAL:
        raise InvalidState(f"lead is {lead.status}, only pending_approval leads can be approved")

    draft = dict(lead.crm_draft or {})
    edits = {k: v for k, v in data.model_dump(exclude={"reviewer"}).items() if v is not None}
    draft.update(edits)
    lead.crm_draft = draft

    q = lead.qualification or {}
    contact = CrmContact(
        email=lead.email, first_name=lead.first_name, last_name=lead.last_name,
        company=lead.company, phone=lead.phone, website=(lead.enrichment or {}).get("website") or lead.website,
        job_title=lead.job_title, stage=draft.get("stage", "lead"), score=lead.score or 0,
        tier=lead.tier or "cold", use_case=q.get("use_case", ""), source=lead.source,
    )
    note = (
        f"{draft.get('note', '')}\n\nScore breakdown: "
        + ", ".join(f"{i['rule']} {i['points']:+d}" for i in (lead.score_breakdown or []))
        + f"\n\nSuggested reply ({draft.get('reply_subject', '')}):\n{draft.get('reply_body', '')}"
        + f"\n\nApproved by {data.reviewer} via LeadPilot"
    )
    try:
        res = crm.upsert_contact(contact)
        crm.add_note(res.crm_id, note)
    except CrmError as exc:
        lead.last_error = str(exc)[:2000]
        log_event(s, lead.id, "crm_error", {"provider": crm.name, "error": lead.last_error})
        s.commit()
        raise

    now = datetime.now(timezone.utc)
    lead.status = LeadStatus.SYNCED
    lead.crm_provider, lead.crm_id = crm.name, res.crm_id
    lead.reviewed_by, lead.reviewed_at, lead.synced_at = data.reviewer, now, now
    lead.last_error = None
    log_event(s, lead.id, "approved", {"reviewer": data.reviewer, "edited_fields": sorted(edits)})
    log_event(s, lead.id, "crm_synced", {"provider": crm.name, "crm_id": res.crm_id, "created": res.created})
    s.commit()
    return lead


def reject_lead(s: Session, lead: Lead, data: RejectIn) -> Lead:
    if lead.status != LeadStatus.PENDING_APPROVAL:
        raise InvalidState(f"lead is {lead.status}, only pending_approval leads can be rejected")
    lead.status = LeadStatus.REJECTED
    lead.reviewed_by, lead.reviewed_at = data.reviewer, datetime.now(timezone.utc)
    log_event(s, lead.id, "rejected", {"reviewer": data.reviewer, "reason": data.reason})
    s.commit()
    return lead
