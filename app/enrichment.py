"""Enrichment agent tools: deterministic, free, no third-party data vendor required.

- email domain classification (business / free webmail / disposable)
- company website fetch: <title>, meta description, reachability
Swap in Clearbit/Apollo/People Data Labs here if the client pays for one.
"""

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.fr", "hotmail.com", "hotmail.fr", "outlook.com",
    "outlook.fr", "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com",
    "gmx.com", "gmx.de", "mail.com", "yandex.com", "yandex.ru", "orange.fr", "free.fr", "laposte.net",
    "sfr.fr", "wanadoo.fr", "zoho.com", "qq.com", "163.com",
}
DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "temp-mail.org",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com", "dispostable.com", "maildrop.cc",
}

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*content=["\']([^"\']*)["\']', re.I
)
_DESC_RE_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:name|property)=["\'](?:description|og:description)["\']', re.I
)


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower().strip()


def classify_domain(domain: str) -> str:
    if domain in DISPOSABLE_DOMAINS:
        return "disposable"
    if domain in FREE_EMAIL_DOMAINS:
        return "free"
    return "business"


def normalize_website(website: str | None, domain: str, domain_type: str) -> str | None:
    if website:
        w = website.strip()
        if not w.startswith(("http://", "https://")):
            w = "https://" + w
        return w
    if domain_type == "business":
        return f"https://{domain}"
    return None


def _clean(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def is_public_host(host: str) -> bool:
    """SSRF guard: lead-supplied URLs must resolve to public IPs only."""
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast \
                or ip.is_unspecified:
            return False
    return True


def fetch_site_meta(url: str, client: httpx.Client, max_redirects: int = 3) -> dict:
    headers = {"User-Agent": "LeadPilot/1.0 (+lead enrichment)"}
    try:
        for _ in range(max_redirects + 1):
            if urlparse(url).scheme not in ("http", "https") or not is_public_host(urlparse(url).hostname or ""):
                return {"reachable": False, "error": "blocked_host"}
            resp = client.get(url, follow_redirects=False, headers=headers)
            if resp.is_redirect and "location" in resp.headers:
                url = urljoin(url, resp.headers["location"])
                continue
            break
    except httpx.HTTPError as exc:
        return {"reachable": False, "error": type(exc).__name__}
    if resp.status_code >= 400 or resp.is_redirect:
        return {"reachable": False, "status_code": resp.status_code}
    html = resp.text[:200_000]
    title = _TITLE_RE.search(html)
    desc = _DESC_RE.search(html) or _DESC_RE_REV.search(html)
    return {
        "reachable": True,
        "final_url": str(resp.url),
        "title": _clean(title.group(1), 200) if title else None,
        "description": _clean(desc.group(1), 400) if desc else None,
    }


def enrich_lead(lead: dict, *, fetch_website: bool, client: httpx.Client | None) -> dict:
    domain = email_domain(lead["email"])
    domain_type = classify_domain(domain)
    website = normalize_website(lead.get("website"), domain, domain_type)
    company_guess = lead.get("company") or (domain.split(".")[0].capitalize() if domain_type == "business" else None)

    out = {
        "email_domain": domain,
        "domain_type": domain_type,
        "website": website,
        "company_guess": company_guess,
        "site": None,
    }
    if website and fetch_website and client is not None:
        out["site"] = fetch_site_meta(website, client)
    return out
