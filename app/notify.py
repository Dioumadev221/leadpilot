import logging

import httpx

log = logging.getLogger(__name__)


def post_slack(webhook_url: str, text: str) -> bool:
    """Best effort: a Slack outage must never break the pipeline."""
    try:
        httpx.post(webhook_url, json={"text": text}, timeout=5).raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.warning("slack notification failed: %s", exc)
        return False
