"""HubSpot CRM v3 adapter (private app token, free CRM works).

Required private-app scopes: crm.objects.contacts.read, crm.objects.contacts.write.
"""

from datetime import datetime, timezone

import httpx

from app.crm.base import CrmContact, CrmError, CrmResult, request_with_retry

LIFECYCLE = {"sql": "salesqualifiedlead", "mql": "marketingqualifiedlead", "lead": "lead"}
NOTE_TO_CONTACT = 202  # HubSpot-defined association type id


class HubSpotAdapter:
    name = "hubspot"
    base_url = "https://api.hubapi.com"

    def __init__(self, token: str, client: httpx.Client | None = None, sleep=None):
        if not token:
            raise CrmError("HUBSPOT_TOKEN is not set")
        self.client = client or httpx.Client(timeout=15)
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._kw = {"sleep": sleep} if sleep else {}

    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        return request_with_retry(self.client, method, self.base_url + path, headers=self.headers, **self._kw, **kwargs)

    def _find_by_email(self, email: str) -> str | None:
        body = {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
                "properties": ["email"], "limit": 1}
        results = self._req("POST", "/crm/v3/objects/contacts/search", json=body).json().get("results", [])
        return results[0]["id"] if results else None

    def upsert_contact(self, c: CrmContact) -> CrmResult:
        props = {
            "email": c.email,
            "firstname": c.first_name,
            "lastname": c.last_name,
            "company": c.company,
            "phone": c.phone,
            "website": c.website,
            "jobtitle": c.job_title,
            "hs_lead_status": "NEW",
        }
        props = {k: v for k, v in props.items() if v}
        existing = self._find_by_email(c.email)
        if existing:
            # HubSpot rejects moving lifecyclestage backwards, so only set it on create.
            self._req("PATCH", f"/crm/v3/objects/contacts/{existing}", json={"properties": props})
            return CrmResult(crm_id=existing, created=False)
        props["lifecyclestage"] = LIFECYCLE[c.stage]
        data = self._req("POST", "/crm/v3/objects/contacts", json={"properties": props}).json()
        return CrmResult(crm_id=str(data["id"]), created=True)

    def add_note(self, crm_id: str, body: str) -> None:
        payload = {
            "properties": {
                "hs_timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "hs_note_body": body.replace("\n", "<br>"),
            },
            "associations": [{
                "to": {"id": crm_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": NOTE_TO_CONTACT}],
            }],
        }
        self._req("POST", "/crm/v3/objects/notes", json=payload)
