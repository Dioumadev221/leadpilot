from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.graph import build_graph
from app.scoring import score_lead

HOT = dict(email="sarah@northwindlegal.com", first_name="Sarah", company="Northwind Legal", job_title="COO",
           source="website", message="We need a RAG assistant over 40k contracts with cited answers. "
           "Budget is around $15k, we want it live this quarter.")
SPAM = dict(email="growth@rankboost.net", source="website",
            message="We can rank your website on Google with high quality backlinks and guest posts.")
VAGUE = dict(email="maria@outlook.com", source="malt", message="Maybe next year we will need something.")


def run(graph, lead):
    return graph.invoke({"lead": lead, "warnings": [], "trace": []})


def test_hot_lead_goes_to_approval_with_draft(graph):
    out = run(graph, HOT)
    assert out["status"] == "pending_approval"
    assert out["tier"] == "hot" and out["score"] >= 70
    q = out["qualification"]
    assert q["use_case"] == "RAG chatbot" and q["budget_signal"] == "stated" and q["timeline"] == "this_quarter"
    assert out["crm_draft"]["stage"] == "sql"
    assert "Sarah" in out["crm_draft"]["reply_body"]
    assert [t["step"] for t in out["trace"]] == ["enrich", "qualify", "score", "draft"]


def test_spam_is_auto_rejected_and_never_drafted(graph):
    out = run(graph, SPAM)
    assert out["status"] == "auto_rejected" and out["tier"] == "spam" and out["score"] == 0
    assert "crm_draft" not in out


def test_disposable_email_is_spam(graph):
    out = run(graph, dict(email="x@yopmail.com", message="I need a chatbot for my business, budget $5k"))
    assert out["status"] == "auto_rejected"


def test_vague_free_email_lead_is_cold(graph):
    out = run(graph, VAGUE)
    assert out["status"] == "pending_approval" and out["tier"] == "cold"
    assert out["crm_draft"]["stage"] == "lead"


def test_score_is_deterministic_and_explained():
    enrichment = {"domain_type": "business", "site": {"reachable": True}}
    q = {"intent": "high", "icp_fit": "strong", "budget_signal": "stated", "budget_amount": "$15k",
         "timeline": "this_quarter"}
    s1, b1 = score_lead(HOT, enrichment, q)
    s2, _ = score_lead(HOT, enrichment, q)
    assert s1 == s2 == 15 + 5 + 15 + 25 + 15 + 15 + 6
    assert sum(i["points"] for i in b1) == s1


def test_broken_llm_falls_back_to_heuristics(settings):
    # A model returning garbage must not kill the pipeline.
    bad_llm = FakeListChatModel(responses=["not json at all"] * 4)
    out = build_graph(settings, llm=bad_llm).invoke({"lead": HOT, "warnings": [], "trace": []})
    assert out["status"] == "pending_approval"
    assert out["qualification"]["mode"] == "heuristic"
    assert any("fell back" in w for w in out["warnings"])
