import pytest

from app.agents import _amount
from app.enrichment import is_public_host
from app.models import Lead

LEAD = {"email": "c.wright@helixbio.com", "first_name": "Chloe", "company": "Helix Bio",
        "message": "We need document processing for lab reports. Budget $10k, this quarter."}


@pytest.fixture
def st(client):
    return client.app.state.settings


def test_pages_and_meta(client):
    assert "Every inbound lead" in client.get("/").text
    assert "LeadPilot" in client.get("/app").text
    assert client.get("/favicon.ico").headers["content-type"].startswith("image/svg")
    meta = client.get("/api/meta").json()
    assert meta["crm"] == "mock" and meta["llm"] == "rules" and meta["hot_threshold"] == 70


def test_contact_and_public_url_are_injected(client, st, monkeypatch):
    monkeypatch.setattr(st, "contact_url", "https://example.com/hire")
    monkeypatch.setattr(st, "public_url", "https://leadpilot.example.com/")
    html = client.get("/").text
    assert "{{CONTACT_URL}}" not in html and "https://example.com/hire" in html
    assert 'content="https://leadpilot.example.com/static/img/og.png"' in html


def test_inline_processing_returns_processed_lead(client, st, monkeypatch):
    monkeypatch.setattr(st, "inline_processing", True)
    body = client.post("/api/leads", json=LEAD).json()
    assert body["status"] == "pending_approval" and body["tier"] in {"hot", "warm"}


def test_demo_rate_limit_per_ip(client, st, monkeypatch):
    monkeypatch.setattr(st, "demo_mode", True)
    monkeypatch.setattr(st, "demo_submissions_per_hour", 2)
    ip = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(2):
        assert client.post("/api/leads", json=LEAD, headers=ip).status_code == 201
    assert client.post("/api/leads", json=LEAD, headers=ip).status_code == 429
    assert client.post("/api/leads", json=LEAD, headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 201


def test_cron_requires_secret(client, st, monkeypatch):
    assert client.get("/api/cron/daily").status_code == 401  # no secret configured: endpoint closed
    monkeypatch.setattr(st, "cron_secret", "s3cret")
    assert client.get("/api/cron/daily", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_cron_resets_demo_workspace(client, st, monkeypatch, session_factory):
    from app.demo import SAMPLE_LEADS

    monkeypatch.setattr(st, "cron_secret", "s3cret")
    monkeypatch.setattr(st, "demo_mode", True)
    client.post("/api/leads", json=LEAD)
    r = client.get("/api/cron/daily", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200, r.text
    assert r.json()["demo_reseeded"] == len(SAMPLE_LEADS) and r.json()["report"]
    with session_factory() as s:
        assert s.query(Lead).count() == len(SAMPLE_LEADS)
        assert s.query(Lead).filter(Lead.email == LEAD["email"], Lead.first_name == "Chloe").count() == 1
    assert client.get("/api/reports/latest").status_code == 200


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.5", "169.254.169.254", "0.0.0.0", "::1"])
def test_ssrf_guard_blocks_internal_hosts(host):
    assert not is_public_host(host)


@pytest.mark.parametrize("text,expected", [("Budget is around $15k, live soon", "$15k"),
                                           ("Budget 6000€, démarrage", "6000€")])
def test_budget_amount_extraction(text, expected):
    assert _amount(text) == expected
