"""LangGraph pipeline: enrich -> qualify -> score -> (spam? stop) -> draft.

A bounded DAG, not an open-ended agent loop: every lead takes at most 4 steps,
cost per lead is predictable, and there is no way for the agents to loop.
The graph never writes to the CRM. It stops at `pending_approval` and a human decides.
"""

import logging
import time
from functools import wraps
from typing import Any, TypedDict

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app import agents
from app.config import Settings
from app.enrichment import enrich_lead
from app.scoring import STAGE_FOR_TIER, score_lead, tier_for

log = logging.getLogger(__name__)


class LeadState(TypedDict, total=False):
    lead: dict
    enrichment: dict
    qualification: dict
    score: int
    score_breakdown: list[dict]
    tier: str
    crm_draft: dict
    status: str
    warnings: list[str]
    trace: list[dict]


def timed(fn):
    """Adds the step's wall-clock duration to the trace entry it appends."""
    @wraps(fn)
    def run(state):
        t0 = time.perf_counter()
        out = fn(state)
        out["trace"][-1]["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out
    return run


def build_graph(settings: Settings, llm: BaseChatModel | None = None, http_client: httpx.Client | None = None):
    def enrich(state: LeadState) -> dict[str, Any]:
        e = enrich_lead(state["lead"], fetch_website=settings.enrich_fetch_website, client=http_client)
        return {"enrichment": e, "trace": [*state.get("trace", []), {"step": "enrich", "domain_type": e["domain_type"]}]}

    def qualify(state: LeadState) -> dict[str, Any]:
        warnings = list(state.get("warnings", []))
        mode = "heuristic"
        q = None
        if llm is not None:
            try:
                q = agents.qualify_with_llm(llm, state["lead"], state["enrichment"], settings.icp_description)
                mode = "llm"
            except Exception as exc:  # provider outage, bad JSON, timeout...
                log.warning("qualifier LLM failed, falling back: %s", exc)
                warnings.append(f"qualifier fell back to heuristics: {type(exc).__name__}")
        if q is None:
            q = agents.qualify_heuristic(state["lead"], state["enrichment"])
        data = q.model_dump() | {"mode": mode}
        return {"qualification": data, "warnings": warnings,
                "trace": [*state.get("trace", []), {"step": "qualify", "mode": mode, "intent": q.intent}]}

    def score(state: LeadState) -> dict[str, Any]:
        q = state["qualification"]
        total, breakdown = score_lead(state["lead"], state["enrichment"], q)
        spam = q["is_spam"] or state["enrichment"]["domain_type"] == "disposable"
        tier = "spam" if spam else tier_for(total, settings.hot_threshold, settings.warm_threshold)
        return {"score": 0 if spam else total, "score_breakdown": breakdown, "tier": tier,
                "status": "auto_rejected" if spam else "pending_approval",
                "trace": [*state.get("trace", []), {"step": "score", "score": total, "tier": tier}]}

    def draft(state: LeadState) -> dict[str, Any]:
        warnings = list(state.get("warnings", []))
        args = (state["lead"], state["enrichment"], state["qualification"], state["score"], state["tier"])
        d, mode = None, "template"
        if llm is not None:
            try:
                d = agents.draft_with_llm(llm, *args)
                mode = "llm"
            except Exception as exc:
                log.warning("writer LLM failed, falling back: %s", exc)
                warnings.append(f"writer fell back to template: {type(exc).__name__}")
        if d is None:
            d = agents.draft_template(*args)
        data = d.model_dump() | {"stage": STAGE_FOR_TIER[state["tier"]], "mode": mode}
        return {"crm_draft": data, "warnings": warnings,
                "trace": [*state.get("trace", []), {"step": "draft", "mode": mode}]}

    def route_after_score(state: LeadState) -> str:
        return END if state["status"] == "auto_rejected" else "draft"

    g = StateGraph(LeadState)
    g.add_node("enrich", timed(enrich))
    g.add_node("qualify", timed(qualify))
    g.add_node("score", timed(score))
    g.add_node("draft", timed(draft))
    g.add_edge(START, "enrich")
    g.add_edge("enrich", "qualify")
    g.add_edge("qualify", "score")
    g.add_conditional_edges("score", route_after_score, {"draft": "draft", END: END})
    g.add_edge("draft", END)
    return g.compile()
