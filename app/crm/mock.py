from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.crm.base import CrmContact, CrmResult
from app.models import MockCrmRecord


class MockCrmAdapter:
    """Writes to a local table. Lets the demo and the tests run the full approval flow."""

    name = "mock"

    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory

    def upsert_contact(self, c: CrmContact) -> CrmResult:
        with self.session_factory() as s:
            rec = s.scalar(select(MockCrmRecord).where(MockCrmRecord.email == c.email))
            created = rec is None
            if created:
                rec = MockCrmRecord(email=c.email, properties={}, notes=[])
                s.add(rec)
            rec.properties = {**rec.properties, **{k: v for k, v in c.__dict__.items() if v is not None}}
            s.commit()
            return CrmResult(crm_id=f"mock-{rec.id}", created=created)

    def add_note(self, crm_id: str, body: str) -> None:
        with self.session_factory() as s:
            rec = s.get(MockCrmRecord, int(crm_id.removeprefix("mock-")))
            rec.notes = [*rec.notes, body]
            s.commit()
