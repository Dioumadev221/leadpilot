import json

import httpx
import pytest

from app.crm.base import CrmContact, CrmError
from app.crm.hubspot import HubSpotAdapter
from app.crm.zoho import ZohoAdapter

C = CrmContact(email="sarah@northwind.com", first_name="Sarah", last_name="Kim", company="Northwind", phone=None,
               website="https://northwind.com", job_title="COO", stage="sql", score=88, tier="hot",
               use_case="RAG chatbot", source="website")


def recorder(handler):
    calls = []

    def wrapped(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content or b"{}"), req))
        return handler(req, len(calls))
    return calls, httpx.Client(transport=httpx.MockTransport(wrapped))


def test_hubspot_creates_contact_and_note():
    def handler(req, n):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": []})
        if req.url.path == "/crm/v3/objects/contacts":
            return httpx.Response(201, json={"id": "501"})
        return httpx.Response(201, json={"id": "9"})
    calls, client = recorder(handler)
    hs = HubSpotAdapter("tok", client=client)
    res = hs.upsert_contact(C)
    hs.add_note(res.crm_id, "line1\nline2")
    assert res.crm_id == "501" and res.created
    create = calls[1][2]["properties"]
    assert create["lifecyclestage"] == "salesqualifiedlead" and create["email"] == C.email and "phone" not in create
    note = calls[2][2]
    assert note["associations"][0]["types"][0]["associationTypeId"] == 202
    assert note["properties"]["hs_note_body"] == "line1<br>line2"
    assert calls[0][3].headers["authorization"] == "Bearer tok"


def test_hubspot_updates_existing_without_lifecycle():
    def handler(req, n):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"results": [{"id": "77"}]})
        return httpx.Response(200, json={"id": "77"})
    calls, client = recorder(handler)
    res = HubSpotAdapter("tok", client=client).upsert_contact(C)
    assert (res.crm_id, res.created) == ("77", False)
    assert calls[1][0] == "PATCH" and "lifecyclestage" not in calls[1][2]["properties"]


def test_hubspot_retries_on_429_then_raises_on_4xx():
    def handler(req, n):
        if n == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(400, json={"message": "bad property"})
    _, client = recorder(handler)
    with pytest.raises(CrmError, match="400"):
        HubSpotAdapter("tok", client=client, sleep=lambda _: None).upsert_contact(C)


def test_zoho_refreshes_token_and_upserts():
    def handler(req, n):
        if "oauth" in req.url.path:
            return httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        if req.url.path.endswith("/Leads/upsert"):
            return httpx.Response(200, json={"data": [{"status": "success", "action": "insert",
                                                       "details": {"id": "4200"}}]})
        return httpx.Response(201, json={"data": [{"status": "success"}]})
    calls, client = recorder(handler)
    z = ZohoAdapter("cid", "sec", "rt", dc="eu", client=client)
    res = z.upsert_contact(C)
    z.add_note(res.crm_id, "note")
    assert res.crm_id == "4200" and res.created
    assert calls[0][3].url.host == "accounts.zoho.eu"
    upsert = calls[1]
    assert upsert[3].headers["authorization"] == "Zoho-oauthtoken at-1"
    assert upsert[2]["duplicate_check_fields"] == ["Email"] and upsert[2]["data"][0]["Lead_Status"] == "Pre-Qualified"
    assert calls[2][1] == "/crm/v6/Leads/4200/Notes"
    assert sum(1 for c in calls if "oauth" in c[1]) == 1  # token cached
