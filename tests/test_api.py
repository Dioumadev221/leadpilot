from app.models import MockCrmRecord
from app.services import process_pending

LEAD = {"email": "d.osei@finlytics.co", "first_name": "Daniel", "company": "Finlytics", "job_title": "CTO",
        "message": "We need multi-agent LangGraph workflows for financial report extraction. Budget $25k, ASAP."}


def test_full_flow_create_process_approve_sync(client, session_factory):
    r = client.post("/api/leads", json=LEAD)
    assert r.status_code == 201
    lead_id = r.json()["id"]

    lead = client.get(f"/api/leads/{lead_id}").json()  # processed by the background task
    assert lead["status"] == "pending_approval" and lead["tier"] == "hot"
    kinds = [e["kind"] for e in lead["events"]]
    assert kinds[:2] == ["received", "agent.enrich"]

    r = client.post(f"/api/leads/{lead_id}/approve", json={"reviewer": "diouma", "reply_subject": "Edited subject"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "synced" and body["crm_id"].startswith("mock-")
    assert body["crm_draft"]["reply_subject"] == "Edited subject"

    with session_factory() as s:
        rec = s.query(MockCrmRecord).one()
        assert rec.email == LEAD["email"] and rec.properties["stage"] == "sql"
        assert "Approved by diouma" in rec.notes[0]

    assert client.post(f"/api/leads/{lead_id}/approve", json={}).status_code == 409


def test_idempotency_key_dedupes(client):
    h = {"Idempotency-Key": "form-123"}
    a = client.post("/api/leads", json=LEAD, headers=h).json()
    b = client.post("/api/leads", json=LEAD, headers=h).json()
    assert a["id"] == b["id"]


def test_webhook_maps_form_fields(client):
    r = client.post("/api/webhooks/lead?source=webflow", data={
        "Email": "jay@carefirstclinics.com", "name": "Jay Patel", "Company": "CareFirst",
        "Message": "Looking for an AI voice agent to handle appointment booking. Twilio in place. ASAP."})
    assert r.status_code == 202
    lead = client.get(f"/api/leads/{r.json()['id']}").json()
    assert (lead["first_name"], lead["last_name"], lead["source"]) == ("Jay", "Patel", "webflow")
    assert lead["qualification"]["use_case"] == "AI voice agent"


def test_webhook_rejects_bad_email(client):
    assert client.post("/api/webhooks/lead", json={"email": "nope", "message": "hi"}).status_code == 422


def test_reject_and_reprocess(client):
    lead_id = client.post("/api/leads", json={**LEAD, "email": "a@b-corp.com"}).json()["id"]
    assert client.post(f"/api/leads/{lead_id}/reject", json={"reason": "budget"}).json()["status"] == "rejected"
    assert client.post(f"/api/leads/{lead_id}/reprocess").status_code == 200
    assert client.get(f"/api/leads/{lead_id}").json()["status"] == "pending_approval"


def test_worker_retries_then_fails(client, session_factory, settings):
    class Boom:
        def invoke(self, _):
            raise RuntimeError("provider down")

    from app.main import app
    app.state.graph = Boom()
    lead_id = client.post("/api/leads", json={**LEAD, "email": "z@zeta.io"}).json()["id"]
    for _ in range(settings.max_attempts):
        process_pending(session_factory, Boom(), settings)
    lead = client.get(f"/api/leads/{lead_id}").json()
    assert lead["status"] == "failed" and lead["attempts"] == settings.max_attempts
    assert "provider down" in lead["last_error"]


def test_weekly_report_numbers_match_db(client):
    for i, msg in enumerate(["We need a RAG chatbot, budget $8k, ASAP.", "SEO backlinks for your site",
                             "We need CRM automation with HubSpot this month, budget 5000€"]):
        client.post("/api/leads", json={"email": f"p{i}@co{i}.com", "message": msg, "source": "upwork"})
    r = client.post("/api/reports/generate")
    assert r.status_code == 200
    m = r.json()["metrics"]
    assert m["total_leads"] == 3 and m["spam_filtered"] == 1 and m["by_source"] == {"upwork": 3}
    assert len(r.json()["narrative"]["actions"]) == 3
    assert client.get("/api/reports/latest").json()["id"] == r.json()["id"]


def test_api_key_enforced(client):
    from app.main import app
    app.state.settings.api_key = "secret"
    try:
        assert client.get("/api/leads").status_code == 401
        assert client.get("/api/leads", headers={"X-API-Key": "secret"}).status_code == 200
    finally:
        app.state.settings.api_key = ""
