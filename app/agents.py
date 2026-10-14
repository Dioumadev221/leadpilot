"""The two LLM agents (qualifier, writer) and their deterministic fallbacks.

Each agent uses structured output (Pydantic schema), so the graph never parses free text.
If the LLM call fails or no provider is set, the heuristic version runs and a warning is recorded.
"""

import re

from langchain_core.language_models.chat_models import BaseChatModel

from app.schemas import CrmDraft, Qualification

QUALIFIER_SYSTEM = """You are a B2B lead qualification analyst for an AI & backend development consultancy.
Ideal customer profile (ICP): {icp}

Extract buying signals from the inbound lead. Rules:
- Use ONLY what the lead wrote and the enrichment data. Never invent budget, company size or timeline.
- If a field is not stated, use "none" / "unknown".
- Mark is_spam for SEO/link-building/marketing pitches, people selling services TO us, job seekers, tests and gibberish.
- In reasoning, quote the lead's own words."""

WRITER_SYSTEM = """You write for a senior AI & backend consultant. Be specific, concise, no hype, no emojis.
The CRM note is for the sales pipeline. The reply email goes to the lead and must:
- reference their actual need in one sentence,
- ask at most two sharp qualifying questions,
- propose a 20-minute call,
- stay under 120 words, signed "Diouma"."""


def _lead_block(lead: dict, enrichment: dict) -> str:
    site = enrichment.get("site") or {}
    return (
        f"Name: {lead.get('first_name') or ''} {lead.get('last_name') or ''}\n"
        f"Email domain: {enrichment['email_domain']} ({enrichment['domain_type']})\n"
        f"Company: {lead.get('company') or enrichment.get('company_guess') or 'unknown'}\n"
        f"Job title: {lead.get('job_title') or 'unknown'}\n"
        f"Website: {enrichment.get('website') or 'none'} | title: {site.get('title') or '-'} | "
        f"description: {site.get('description') or '-'}\n"
        f"Source: {lead.get('source')}\n"
        f"Message:\n\"\"\"\n{lead.get('message') or ''}\n\"\"\""
    )


# ---------------- qualifier ----------------

def qualify_with_llm(llm: BaseChatModel, lead: dict, enrichment: dict, icp: str) -> Qualification:
    structured = llm.with_structured_output(Qualification)
    return structured.invoke([
        ("system", QUALIFIER_SYSTEM.format(icp=icp)),
        ("human", _lead_block(lead, enrichment)),
    ])


SPAM_PATTERNS = [r"\bseo\b", r"backlink", r"guest post", r"link building", r"rank (your|on) google",
                 r"we (are|re) an? (agency|outsourcing)", r"offshore team", r"crypto", r"casino", r"viagra",
                 r"^\W*test\W*$", r"lorem ipsum", r"looking for a job", r"\bhire me\b", r"my resume"]
HIGH_INTENT = [r"\bneed\b", r"looking for", r"\bhire\b", r"\bbuild\b", r"asap", r"urgent", r"proposal", r"quote",
               r"\bbudget\b", r"\bdeadline\b", r"start (next|this) (week|month)", r"\bdevis\b", r"besoin"]
MEDIUM_INTENT = [r"exploring", r"interested", r"curious", r"thinking about", r"considering", r"maybe", r"could you"]
# Most specific first: on a tie, the earlier category wins.
ICP_KEYWORDS = {
    "AI voice agent": [r"\bvoice\b", r"phone (agent|bot|line|calls?)", r"inbound calls", r"answer(ing)? (the )?calls", r"vapi", r"twilio", r"elevenlabs", r"receptionist"],
    "RAG chatbot": [r"\brag\b", r"chatbot", r"chat with", r"knowledge base", r"documents?", r"retrieval", r"vector"],
    "CRM automation": [r"\bcrm\b", r"hubspot", r"zoho", r"salesforce", r"pipedrive", r"automat", r"n8n", r"zapier", r"workflow"],
    "Backend / API": [r"\bapi\b", r"backend", r"fastapi", r"postgres", r"database", r"scal", r"docker", r"aws", r"gcp"],
    "AI agent": [r"\bagents?\b", r"agentic", r"langgraph", r"langchain", r"crewai", r"\bmcp\b", r"llm", r"gpt", r"openai"],
}
BUDGET_RE = re.compile(
    r"\d[\d,.\s]*k?\s?(?:\$|€|£|usd|eur|dollars|euros)"      # 6000€, 15k USD
    r"|(?:\$|€|£)\s?\d[\d,.\s]*k?"                           # $15k
    r"|budget\D{0,20}\d[\d,.\s]*k?(?:\s?(?:\$|€|£|usd|eur))?",  # budget is around 8000
    re.I,
)


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def qualify_heuristic(lead: dict, enrichment: dict) -> Qualification:
    text = f"{lead.get('message') or ''} {lead.get('job_title') or ''}"
    low = text.lower()

    is_spam = _any(SPAM_PATTERNS, low) or enrichment["domain_type"] == "disposable" or len(low.strip()) < 3
    hits = {name: sum(bool(re.search(p, low, re.I)) for p in pats) for name, pats in ICP_KEYWORDS.items()}
    use_cases = sorted((n for n in hits if hits[n]), key=lambda n: -hits[n])  # stable sort keeps specificity order
    intent = "high" if _any(HIGH_INTENT, low) else "medium" if (_any(MEDIUM_INTENT, low) or use_cases) else "low"

    budget_match = BUDGET_RE.search(text)
    budget_signal = "stated" if budget_match else ("implied" if re.search(r"paid|pay|invest|retainer", low) else "none")

    if re.search(r"asap|urgent|this week|next week|immediately|tout de suite|cette semaine|semaine prochaine|prochaine semaine|dès que possible", low):
        timeline = "immediate"
    elif re.search(r"this month|next month|this quarter|q[1-4]\b|within \d+ (weeks|days)|end of (this|next) month|ce mois|mois prochain|ce trimestre", low):
        timeline = "this_quarter"
    elif re.search(r"next year|later|someday|eventually", low):
        timeline = "later"
    else:
        timeline = "unknown"

    if is_spam:
        icp_fit = "none"
    elif use_cases and enrichment["domain_type"] == "business":
        icp_fit = "strong"
    elif use_cases:
        icp_fit = "partial"
    else:
        icp_fit = "none"

    use_case = use_cases[0] if use_cases else "Unclear"
    first_sentence = re.split(r"(?<=[.!?])\s", (lead.get("message") or "").strip())[0][:240]
    return Qualification(
        is_spam=is_spam,
        intent="low" if is_spam else intent,
        icp_fit=icp_fit,
        budget_signal=budget_signal,
        budget_amount=budget_match.group(0).strip(" ,.") if budget_match else None,
        timeline=timeline,
        use_case=use_case,
        need_summary=first_sentence or "No message provided.",
        recommended_action=(
            "Discard" if is_spam else
            "Book a discovery call within 24h" if intent == "high" else
            "Reply with 2 qualifying questions" if intent == "medium" else
            "Add to nurture sequence"
        ),
        reasoning=f"Heuristic rules matched use cases {use_cases or 'none'}; intent={intent}; budget={budget_signal}.",
    )


# ---------------- writer ----------------

def draft_with_llm(llm: BaseChatModel, lead: dict, enrichment: dict, q: dict, score: int, tier: str) -> CrmDraft:
    structured = llm.with_structured_output(CrmDraft)
    return structured.invoke([
        ("system", WRITER_SYSTEM),
        ("human", f"{_lead_block(lead, enrichment)}\n\nQualification: {q}\nScore: {score}/100 ({tier})"),
    ])


def draft_template(lead: dict, enrichment: dict, q: dict, score: int, tier: str) -> CrmDraft:
    name = lead.get("first_name") or "there"
    company = lead.get("company") or enrichment.get("company_guess") or "your team"
    note = (
        f"[{tier.upper()} {score}/100] {q['use_case']} | intent {q['intent']} | ICP {q['icp_fit']}\n"
        f"Need: {q['need_summary']}\n"
        f"Budget: {q.get('budget_amount') or q['budget_signal']} | Timeline: {q['timeline']}\n"
        f"Next step: {q['recommended_action']}"
    )
    questions = []
    if q["budget_signal"] == "none":
        questions.append("what budget range you have in mind")
    if q["timeline"] in ("unknown", "later"):
        questions.append("when you need it live")
    ask = f" To scope it properly, could you share {' and '.join(questions)}?" if questions else ""
    body = (
        f"Hi {name},\n\n"
        f"Thanks for reaching out about {q['use_case']} for {company}. "
        f"I build exactly this in production (Python/FastAPI, LangGraph, PostgreSQL).{ask}\n\n"
        f"Happy to do a 20-minute call this week to map the architecture and give you a clear estimate.\n\n"
        f"Best,\nDiouma"
    )
    return CrmDraft(note=note, reply_subject=f"Re: {q['use_case']} for {company}", reply_body=body)
