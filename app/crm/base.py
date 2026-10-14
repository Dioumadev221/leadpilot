import time
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx


class CrmError(RuntimeError):
    pass


@dataclass
class CrmContact:
    email: str
    first_name: str | None
    last_name: str | None
    company: str | None
    phone: str | None
    website: str | None
    job_title: str | None
    stage: str          # our vocabulary: "sql" | "mql" | "lead"; each adapter maps it
    score: int
    tier: str
    use_case: str
    source: str


@dataclass
class CrmResult:
    crm_id: str
    created: bool


class CRMAdapter(Protocol):
    """Every CRM integration implements these two calls. Adding Pipedrive or
    Salesforce means one new file, no change to the agents or the API."""

    name: str

    def upsert_contact(self, contact: CrmContact) -> CrmResult: ...

    def add_note(self, crm_id: str, body: str) -> None: ...


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> httpx.Response:
    """Retries 429 and 5xx with exponential backoff, honouring Retry-After."""
    for i in range(attempts):
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if i == attempts - 1:
                raise CrmError(f"{method} {url}: {exc}") from exc
            sleep(2**i)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if i == attempts - 1:
                break
            retry_after = resp.headers.get("Retry-After")
            sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2**i)
            continue
        if resp.status_code >= 400:
            raise CrmError(f"{method} {url} -> {resp.status_code}: {resp.text[:500]}")
        return resp
    raise CrmError(f"{method} {url} -> {resp.status_code} after {attempts} attempts: {resp.text[:300]}")
