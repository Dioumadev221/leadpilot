# Upwork portfolio entry: LeadPilot

> Copy each block into Upwork → Profile → Portfolio → Add project. Images: `docs/screenshots/*.png` (approval-queue first as the cover).

## Project title (max 70 characters)

AI Lead Qualification Agent + HubSpot/Zoho CRM Automation (LangGraph)

## Your role

AI & Backend Developer: architecture, agents, backend, CRM integrations, deployment

## Project description

**Problem.** Small B2B teams get inbound leads from forms, Upwork, LinkedIn and referrals. Someone has to read each one, look up the company, decide if it is worth a call, copy it into the CRM and write a reply. Hot leads wait days, spam clogs the CRM, and nobody knows what the pipeline did last week.

**Solution.** A multi-agent system that does the triage in seconds and keeps a human in control:
- Enrichment agent: email domain type, company website data.
- Qualifier agent (LLM, structured output): intent, ICP fit, budget, timeline, use case, next step, with reasoning that quotes the lead.
- Deterministic scoring rules (0–100) with a per-point breakdown, so the score is auditable and tunable, not an LLM guess.
- Spam and disposable emails are filtered automatically and never reach the CRM.
- Writer agent drafts the CRM note and a tailored first reply.
- Human-in-the-loop console: review, edit, approve. Only approved leads are written to HubSpot or Zoho (contact upsert + note + lifecycle stage).
- Weekly analyst agent: SQL-computed pipeline metrics plus a short narrative and three actions, posted to Slack. The numbers come from the database, never from the model.

**Engineering.** Bounded LangGraph DAG (no agent loops, predictable cost per lead), PostgreSQL job queue with atomic claims and retries, idempotent webhook intake that maps Typeform/Webflow/Zapier/n8n payloads, LLM fallback when the provider fails, CRM adapter interface (new CRM = one file), full audit trail, 18 automated tests on SQLite and PostgreSQL in CI, Dockerized, one-click deploy on Render.

**Results (demo dataset of 12 real-world-style leads).**
- 12 leads enriched, qualified, scored and drafted in 0.16 s in rules mode; with an LLM the cost stays bounded at 2 model calls per lead.
- 3 of 3 spam/vendor/disposable leads filtered automatically.
- Each qualified lead arrives in the CRM with a score, a note and a ready-to-send reply; the reviewer only clicks Approve.
- The weekly report flags hot leads waiting and slow review time automatically.

## Skills (pick up to 5 on Upwork)

AI Agent Development · LangGraph · FastAPI · HubSpot · CRM Automation

(Others to add on the profile: Python, PostgreSQL, LangChain, OpenAI API, Zoho CRM, Docker, REST API.)

## Links

- Live demo: `https://<your-app>.onrender.com`
- Code: `https://github.com/Dioumadev221/leadpilot`

## Short version (for proposals / cover letters)

I built LeadPilot, a multi-agent lead qualification system: LangGraph agents enrich and qualify inbound leads, a deterministic rule engine scores them, spam is filtered, and a human approves before anything is written to HubSpot or Zoho. A weekly analyst agent reports on the pipeline. FastAPI, PostgreSQL, Docker, tested in CI. Demo: <link>.
