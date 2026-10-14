from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LeadStatus:
    RECEIVED = "received"              # queued for the agent pipeline
    PROCESSING = "processing"          # claimed by a worker
    PENDING_APPROVAL = "pending_approval"  # waiting for a human
    SYNCED = "synced"                  # written to the CRM
    REJECTED = "rejected"              # rejected by a human
    AUTO_REJECTED = "auto_rejected"    # spam / disposable, never reaches a human
    FAILED = "failed"                  # pipeline failed max_attempts times

    ALL = [RECEIVED, PROCESSING, PENDING_APPROVAL, SYNCED, REJECTED, AUTO_REJECTED, FAILED]


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source: Mapped[str] = mapped_column(String(64), default="api", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)

    email: Mapped[str] = mapped_column(String(320), index=True)
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    company: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(60))
    job_title: Mapped[str | None] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(32), default=LeadStatus.RECEIVED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    enrichment: Mapped[dict | None] = mapped_column(JSON)
    qualification: Mapped[dict | None] = mapped_column(JSON)
    score: Mapped[int | None] = mapped_column(Integer, index=True)
    score_breakdown: Mapped[list | None] = mapped_column(JSON)
    tier: Mapped[str | None] = mapped_column(String(16), index=True)
    crm_draft: Mapped[dict | None] = mapped_column(JSON)
    warnings: Mapped[list | None] = mapped_column(JSON)

    crm_provider: Mapped[str | None] = mapped_column(String(32))
    crm_id: Mapped[str | None] = mapped_column(String(64))
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["LeadEvent"]] = relationship(
        back_populates="lead", order_by="LeadEvent.id", cascade="all, delete-orphan"
    )


class LeadEvent(Base):
    """Append-only audit trail: every agent step and human decision."""

    __tablename__ = "lead_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    lead: Mapped[Lead] = relationship(back_populates="events")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[dict] = mapped_column(JSON)


class MockCrmRecord(Base):
    """Stand-in CRM so the whole flow runs without a HubSpot/Zoho account."""

    __tablename__ = "mock_crm_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
