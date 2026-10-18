"""Deterministic scoring. The LLM extracts signals; the score itself is a rule table.

Same input, same score, every time, and every point is explained in the breakdown.
That is what a sales team can audit and tune, and what an LLM alone cannot guarantee.
"""

SENIOR_TITLES = ("founder", "co-founder", "ceo", "cto", "coo", "cfo", "owner", "president", "vp", "vice president",
                 "head of", "director", "partner", "chief", "dg", "pdg", "gérant", "directeur", "directrice")
MID_TITLES = ("manager", "lead", "responsable", "product owner", "pm")

RULES = {
    "domain": {"business": 15, "free": 0, "disposable": -30},
    "site_reachable": 5,
    "title_senior": 15,
    "title_mid": 8,
    "intent": {"high": 25, "medium": 12, "low": 0},
    "icp_fit": {"strong": 15, "partial": 7, "none": -10},
    "budget": {"stated": 15, "implied": 8, "none": 0},
    "timeline": {"immediate": 10, "this_quarter": 6, "later": 0, "unknown": 0},
    "short_message": -10,
}


def score_lead(lead: dict, enrichment: dict, q: dict) -> tuple[int, list[dict]]:
    items: list[dict] = []

    def add(rule: str, points: int, why: str):
        if points:
            items.append({"rule": rule, "points": points, "why": why})

    add("domain", RULES["domain"][enrichment["domain_type"]], f"{enrichment['domain_type']} email domain")
    site = enrichment.get("site") or {}
    if site.get("reachable"):
        add("site_reachable", RULES["site_reachable"], "company website is live")

    title = (lead.get("job_title") or "").lower()
    if any(t in title for t in SENIOR_TITLES):
        add("title", RULES["title_senior"], f"decision-maker title: {lead.get('job_title')}")
    elif any(t in title for t in MID_TITLES):
        add("title", RULES["title_mid"], f"mid-level title: {lead.get('job_title')}")

    add("intent", RULES["intent"][q["intent"]], f"{q['intent']} buying intent")
    add("icp_fit", RULES["icp_fit"][q["icp_fit"]], f"{q['icp_fit']} ICP fit")
    add("budget", RULES["budget"][q["budget_signal"]],
        f"budget {q['budget_signal']}" + (f" ({q['budget_amount']})" if q.get("budget_amount") else ""))
    add("timeline", RULES["timeline"][q["timeline"]], f"timeline: {q['timeline'].replace('_', ' ')}")
    if len((lead.get("message") or "").strip()) < 20:
        add("short_message", RULES["short_message"], "message too short to act on")

    total = max(0, min(100, sum(i["points"] for i in items)))
    return total, items


def tier_for(score: int, hot: int, warm: int) -> str:
    if score >= hot:
        return "hot"
    if score >= warm:
        return "warm"
    return "cold"


STAGE_FOR_TIER = {"hot": "sql", "warm": "mql", "cold": "lead"}
