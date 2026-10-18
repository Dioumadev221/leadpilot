"""Sample workspace: a fictional AI studio's inbound pipeline, used by the public live demo.

Everything here is clearly labelled as sample data in the UI. In demo mode the workspace is
wiped and reseeded once a day (Vercel Cron), so visitors always land on a clean pipeline.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.models import Lead, LeadEvent, LeadStatus, MockCrmRecord, Report
from app.schemas import ApproveIn, RejectIn
from app.services import approve_lead, process_pending, reject_lead

# (lead, hours ago)
SAMPLE_LEADS = [
    (dict(email="sarah.kim@northwindlegal.com", first_name="Sarah", last_name="Kim", company="Northwind Legal",
          job_title="COO", source="website",
          message="We need a RAG assistant over ~40k contracts so our associates can ask questions and get cited "
                  "answers. Budget is around $15k, we want it live this quarter. Can you send a proposal?"), 3),
    (dict(email="marc.dubois@atelier-pixel.fr", first_name="Marc", last_name="Dubois", company="Atelier Pixel",
          job_title="Fondateur", source="malt",
          message="Besoin d'automatiser notre CRM HubSpot: qualification des leads entrants et relances. "
                  "Budget 6000€, démarrage la semaine prochaine si possible."), 7),
    (dict(email="j.patel@carefirstclinics.com", first_name="Jay", last_name="Patel", company="CareFirst Clinics",
          job_title="Head of Operations", source="upwork",
          message="Looking for an AI voice agent to handle appointment booking for 6 clinics. We get 300 inbound "
                  "calls a day. Twilio already in place. ASAP."), 26),
    (dict(email="dev@brightcart.io", first_name="Lena", last_name="Moreau", company="BrightCart",
          job_title="Engineering Manager", source="website",
          message="Our FastAPI backend struggles past 2k rps and our previous dev vanished. We need an audit and "
                  "someone to take over the codebase. Paid engagement, starting this month."), 31),
    (dict(email="tom.h@gmail.com", first_name="Tom", last_name="Harris", source="upwork",
          message="Interested in building a chatbot for my small online store, just exploring options for now."), 50),
    (dict(email="ops@zenithlogistics.com", first_name="Priya", last_name="Nair", company="Zenith Logistics",
          job_title="Operations Manager", source="linkedin",
          message="We're considering an agent that reads shipping emails and updates our Zoho CRM. Could you "
                  "explain how you'd approach it?"), 55),
    (dict(email="growth@rankboostseo.net", first_name="Kevin", source="website",
          message="We can rank your website on Google page 1 with high quality backlinks and guest posts. "
                  "Reply for our price list."), 70),
    (dict(email="anna@yopmail.com", first_name="Anna", source="website", message="test"), 74),
    (dict(email="d.osei@finlytics.co", first_name="Daniel", last_name="Osei", company="Finlytics",
          job_title="CTO", source="referral",
          message="We need multi-agent LangGraph workflows for financial report extraction, with evals. "
                  "Budget $25k, deadline end of next month."), 98),
    (dict(email="maria.g@outlook.com", first_name="Maria", last_name="Gomez", source="malt",
          message="Maybe next year we will need some automation for invoices."), 120),
    (dict(email="ben@stackfoundry.dev", first_name="Ben", last_name="Clarke", company="Stack Foundry",
          job_title="Founder", source="upwork",
          message="Need an MCP server + LLM integration for our internal tools. Retainer possible."), 140),
    (dict(email="hello@offshoredevs.co", first_name="Raj", source="linkedin",
          message="We are an outsourcing agency with an offshore team of 50 developers. Let's partner."), 150),
    # Previous week, so week-over-week numbers mean something.
    (dict(email="c.wright@helixbio.com", first_name="Chloe", last_name="Wright", company="Helix Bio",
          job_title="VP Operations", source="website",
          message="We need document processing for lab reports: extract results into our database. "
                  "Budget $10k, this quarter."), 190),
    (dict(email="sam@quickbooksy.io", first_name="Sam", last_name="Lee", company="Quickbooksy",
          job_title="Founder", source="upwork",
          message="Looking for someone to build a support chatbot on our docs. Interested in a quote."), 230),
    (dict(email="info@cheap-links-now.biz", first_name="Mike", source="website",
          message="Guest post and link building offer for your blog, 50 backlinks for $99."), 260),
]

REVIEWER = "Northwind ops"


def seed_demo(session_factory, graph, settings, crm) -> int:
    with session_factory() as s:
        if s.scalar(select(func.count(Lead.id))):
            return 0
        now = datetime.now(timezone.utc)
        for data, hours_ago in SAMPLE_LEADS:
            s.add(Lead(**data, created_at=now - timedelta(hours=hours_ago)))
        s.commit()

    process_pending(session_factory, graph, settings, limit=100)

    with session_factory() as s:
        pending = s.scalars(select(Lead).where(Lead.status == LeadStatus.PENDING_APPROVAL)
                            .order_by(Lead.created_at)).all()
        # The oldest hot/warm leads were already handled by the team; recent ones wait in the queue.
        decided = [lead for lead in pending if (now - _aware(lead.created_at)) > timedelta(hours=40)]
        for i, lead in enumerate(decided):
            if lead.tier == "cold":
                reject_lead(s, lead, RejectIn(reviewer=REVIEWER, reason="Too early, moved to nurture"))
            else:
                approve_lead(s, lead, ApproveIn(reviewer=REVIEWER), crm)
            lead.reviewed_at = _aware(lead.created_at) + timedelta(hours=2 + i % 5)
            if lead.status == LeadStatus.SYNCED:
                lead.synced_at = lead.reviewed_at
        s.commit()
    return len(SAMPLE_LEADS)


def reset_demo(session_factory, graph, settings, crm) -> int:
    with session_factory() as s:
        for model in (LeadEvent, Lead, Report, MockCrmRecord):
            s.execute(delete(model))
        s.commit()
    return seed_demo(session_factory, graph, settings, crm)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
