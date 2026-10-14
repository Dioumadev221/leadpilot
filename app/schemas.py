from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------- inbound ----------

class LeadIn(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    website: str | None = None
    phone: str | None = None
    job_title: str | None = None
    message: str = Field(default="", max_length=10_000)
    source: str = "api"


class ApproveIn(BaseModel):
    reviewer: str = "reviewer"
    # Anything the reviewer edited before approving.
    note: str | None = None
    stage: Literal["sql", "mql", "lead"] | None = None
    reply_subject: str | None = None
    reply_body: str | None = None


class RejectIn(BaseModel):
    reviewer: str = "reviewer"
    reason: str = ""


# ---------- agent outputs (also used as LLM structured-output schemas) ----------

class Qualification(BaseModel):
    """What the qualifier agent extracts from a raw inbound lead."""

    is_spam: bool = Field(description="True for spam, SEO/link-building pitches, tests, gibberish or vendors selling to us.")
    intent: Literal["high", "medium", "low"] = Field(description="How clearly the lead wants to buy a service now.")
    icp_fit: Literal["strong", "partial", "none"] = Field(description="Fit with the ideal customer profile.")
    budget_signal: Literal["stated", "implied", "none"]
    budget_amount: str | None = Field(default=None, description="Budget as written by the lead, if any.")
    timeline: Literal["immediate", "this_quarter", "later", "unknown"]
    use_case: str = Field(description="Short category, e.g. 'RAG chatbot', 'CRM automation', 'AI voice agent'.")
    need_summary: str = Field(description="One or two sentences: what they need and why.")
    recommended_action: str = Field(description="The single next step a salesperson should take.")
    reasoning: str = Field(description="Brief justification citing the lead's own words.")


class CrmDraft(BaseModel):
    """What the writer agent prepares for the human reviewer."""

    note: str = Field(description="CRM note for the sales team: context, need, fit, next step. 3-6 short lines.")
    reply_subject: str
    reply_body: str = Field(description="First reply email to the lead, under 120 words, specific to their message.")


class ReportNarrative(BaseModel):
    headline: str
    summary: str = Field(description="3-5 sentences that only use the numbers provided.")
    risks: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list, description="Three concrete actions for next week.")


# ---------- outbound ----------

class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    at: datetime
    kind: str
    detail: dict


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    source: str
    email: str
    first_name: str | None
    last_name: str | None
    company: str | None
    website: str | None
    job_title: str | None
    message: str
    status: str
    attempts: int
    last_error: str | None
    enrichment: dict | None
    qualification: dict | None
    score: int | None
    score_breakdown: list | None
    tier: str | None
    crm_draft: dict | None
    warnings: list | None
    crm_provider: str | None
    crm_id: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    synced_at: datetime | None


class LeadDetailOut(LeadOut):
    events: list[EventOut] = []


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    period_start: datetime
    period_end: datetime
    metrics: dict
    narrative: dict
