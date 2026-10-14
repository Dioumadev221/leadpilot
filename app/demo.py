"""Realistic sample leads so a fresh deploy shows a populated pipeline and report."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import Lead, LeadStatus
from app.schemas import ApproveIn, RejectIn
from app.services import approve_lead, process_pending, reject_lead

SAMPLE_LEADS = [
    dict(email="sarah.kim@northwindlegal.com", first_name="Sarah", last_name="Kim", company="Northwind Legal",
         job_title="COO", source="website",
         message="We need a RAG assistant over ~40k contracts so our associates can ask questions and get cited "
                 "answers. Budget is around $15k, we want it live this quarter. Can you send a proposal?"),
    dict(email="marc.dubois@atelier-pixel.fr", first_name="Marc", last_name="Dubois", company="Atelier Pixel",
         job_title="Fondateur", source="malt",
         message="Besoin d'automatiser notre CRM HubSpot: qualification des leads entrants et relances. "
                 "Budget 6000€, démarrage la semaine prochaine si possible."),
    dict(email="j.patel@carefirstclinics.com", first_name="Jay", last_name="Patel", company="CareFirst Clinics",
         job_title="Head of Operations", source="upwork",
         message="Looking for an AI voice agent to handle appointment booking for 6 clinics. We get 300 inbound "
                 "calls a day. Twilio already in place. ASAP."),
    dict(email="dev@brightcart.io", first_name="Lena", last_name="Moreau", company="BrightCart",
         job_title="Engineering Manager", source="website",
         message="Our FastAPI backend struggles past 2k rps and our previous dev vanished. We need an audit and "
                 "someone to take over the codebase. Paid engagement, starting this month."),
    dict(email="tom.h@gmail.com", first_name="Tom", last_name="Harris", source="upwork",
         message="Interested in building a chatbot for my small online store, just exploring options for now."),
    dict(email="ops@zenithlogistics.com", first_name="Priya", last_name="Nair", company="Zenith Logistics",
         job_title="Operations Manager", source="linkedin",
         message="We're considering an agent that reads shipping emails and updates our Zoho CRM. Could you "
                 "explain how you'd approach it?"),
    dict(email="growth@rankboostseo.net", first_name="Kevin", source="website",
         message="We can rank your website on Google page 1 with high quality backlinks and guest posts. "
                 "Reply for our price list."),
    dict(email="anna@yopmail.com", first_name="Anna", source="website", message="test"),
    dict(email="d.osei@finlytics.co", first_name="Daniel", last_name="Osei", company="Finlytics",
         job_title="CTO", source="referral",
         message="We need multi-agent LangGraph workflows for financial report extraction, with evals. "
                 "Budget $25k, deadline end of next month."),
    dict(email="maria.g@outlook.com", first_name="Maria", last_name="Gomez", source="malt",
         message="Maybe next year we will need some automation for invoices."),
    dict(email="ben@stackfoundry.dev", first_name="Ben", last_name="Clarke", company="Stack Foundry",
         job_title="Founder", source="upwork",
         message="Need an MCP server + LLM integration for our internal tools. Retainer possible."),
    dict(email="hello@offshoredevs.co", first_name="Raj", source="linkedin",
         message="We are an outsourcing agency with an offshore team of 50 developers. Let's partner."),
]


def seed_demo(session_factory, graph, settings, crm) -> int:
    with session_factory() as s:
        if s.scalar(select(func.count(Lead.id))):
            return 0
        now = datetime.now(timezone.utc)
        for i, data in enumerate(SAMPLE_LEADS):
            # Spread over two weeks so the week-over-week numbers mean something.
            s.add(Lead(**data, created_at=now - timedelta(days=(i * 13) % 12, hours=i * 3)))
        s.commit()

    process_pending(session_factory, graph, settings, limit=100)

    with session_factory() as s:
        pending = s.scalars(select(Lead).where(Lead.status == LeadStatus.PENDING_APPROVAL).order_by(Lead.score.desc())).all()
        for lead in pending[:3]:
            approve_lead(s, lead, ApproveIn(reviewer="demo"), crm)
        for lead in pending[-1:]:
            if lead.tier == "cold":
                reject_lead(s, lead, RejectIn(reviewer="demo", reason="Too early, added to nurture"))
    return len(SAMPLE_LEADS)
