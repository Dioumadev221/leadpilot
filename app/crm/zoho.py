"""Zoho CRM v6 adapter (OAuth refresh-token flow, Leads module).

Create a "Self Client" in https://api-console.zoho.com, scope ZohoCRM.modules.leads.ALL,
ZohoCRM.modules.notes.CREATE, then exchange the grant code for a refresh token once.
"""

import time

import httpx

from app.crm.base import CrmContact, CrmError, CrmResult, request_with_retry

LEAD_STATUS = {"sql": "Pre-Qualified", "mql": "Not Contacted", "lead": "Not Contacted"}


class ZohoAdapter:
    name = "zoho"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, dc: str = "com",
                 client: httpx.Client | None = None, sleep=None):
        if not (client_id and client_secret and refresh_token):
            raise CrmError("ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN must be set")
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self.accounts_url = f"https://accounts.zoho.{dc}"
        self.api_url = f"https://www.zohoapis.{dc}/crm/v6"
        self.client = client or httpx.Client(timeout=15)
        self._kw = {"sleep": sleep} if sleep else {}
        self._token: str | None = None
        self._token_exp = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        resp = request_with_retry(self.client, "POST", f"{self.accounts_url}/oauth/v2/token", params={
            "refresh_token": self.refresh_token, "client_id": self.client_id,
            "client_secret": self.client_secret, "grant_type": "refresh_token",
        }, **self._kw)
        data = resp.json()
        if "access_token" not in data:
            raise CrmError(f"Zoho token refresh failed: {data}")
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _req(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Zoho-oauthtoken {self._access_token()}"}
        return request_with_retry(self.client, method, self.api_url + path, headers=headers, **self._kw, **kwargs)

    def upsert_contact(self, c: CrmContact) -> CrmResult:
        record = {
            "Email": c.email,
            "First_Name": c.first_name,
            "Last_Name": c.last_name or c.email.split("@")[0],  # mandatory in Zoho
            "Company": c.company or "Unknown",                   # mandatory in Zoho
            "Phone": c.phone,
            "Website": c.website,
            "Designation": c.job_title,
            "Lead_Status": LEAD_STATUS[c.stage],
            "Description": f"LeadPilot score {c.score}/100 ({c.tier}) | {c.use_case} | source: {c.source}",
        }
        record = {k: v for k, v in record.items() if v}
        body = {"data": [record], "duplicate_check_fields": ["Email"]}
        row = self._req("POST", "/Leads/upsert", json=body).json()["data"][0]
        if row.get("status") != "success":
            raise CrmError(f"Zoho upsert failed: {row}")
        return CrmResult(crm_id=str(row["details"]["id"]), created=row.get("action") == "insert")

    def add_note(self, crm_id: str, body: str) -> None:
        payload = {"data": [{"Note_Title": "LeadPilot qualification", "Note_Content": body}]}
        self._req("POST", f"/Leads/{crm_id}/Notes", json=payload)
