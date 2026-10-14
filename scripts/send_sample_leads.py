"""Push the sample leads to a running instance through the public webhook.

usage: python scripts/send_sample_leads.py https://your-app.onrender.com [WEBHOOK_SECRET]
"""
import sys

import httpx

sys.path.insert(0, ".")
from app.demo import SAMPLE_LEADS  # noqa: E402

base = sys.argv[1].rstrip("/")
headers = {"X-Webhook-Secret": sys.argv[2]} if len(sys.argv) > 2 else {}
for lead in SAMPLE_LEADS:
    r = httpx.post(f"{base}/api/webhooks/lead?source={lead.get('source', 'script')}", json=lead, headers=headers)
    print(r.status_code, lead["email"], r.json())
