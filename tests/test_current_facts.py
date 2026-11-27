import pytest

from mdt_demo.research.consensus_metrics import compute_run_consensus_metrics
from mdt_demo.research.engine import execute, route_case
from mdt_demo.research.schemas import ResearchCase, RunRequest
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.workflow_designer import infer_semantic_completeness


def case_with_events(*rows):
    data = seed_cases()[0].model_dump(mode="json")
    template = data["timeline"][0]
    data["timeline"] = [
        {**template, "event_id": eid, "event_type": kind, "facts": facts}
        for eid, kind, facts in rows
    ]
    return ResearchCase.model_validate(data)


def review(case, trigger):
    request = RunRequest(case_id=case.case_id, case_version=case.version, trigger_event_id=trigger)
    return execute(case, request, "run_test", lambda *args: None, lambda: False)


@pytest.mark.parametrize("replacement_id,original_id", [("A", "B"), ("B", "A")])
def test_correction_controls_gate_citations_and_specialist_selection(replacement_id, original_id):
    case = case_with_events(
        (replacement_id, "pathology", {"pathology_confirmed": False, "supersedes_event_id": original_id}),
        (original_id, "pathology", {"pathology_confirmed": True}),
        ("C", "treatment", {"treatment_record_complete": True}),
    )
    report = review(case, "C")
    assert report["final_decision"] == "NEED_MORE_INFORMATION"
    assert report["safety"]["missing_information"] == ["pathology_confirmed"]
    assert not report["unresolved_conflicts"]
    assert f"{original_id}:pathology_confirmed" in {ref["evidence_id"] for ref in report["evidence_registry"]}
    for op in report["final_opinions"]:
        assert f"{replacement_id}:pathology_confirmed" in op["evidence_ids"]
        assert f"{original_id}:pathology_confirmed" not in op["evidence_ids"]
    assert infer_semantic_completeness(case, "C")["strict_missing"] == ["pathology_confirmed"]
    assert "pathology" in route_case(case, "C", "adaptive")["selected_agents"]
    if original_id == "A":
        assert review(case, original_id)["final_decision"] == "READY_FOR_REVIEW"


def test_correction_chain_and_unresolved_cycle():
    case = case_with_events(
        ("A", "pathology", {"histology": "Adenocarcinoma", "supersedes_event_id": "B"}),
        ("B", "pathology", {"histology": "pending", "supersedes_event_id": "C"}),
        ("C", "pathology", {"histology": "pending"}),
    )
    inferred, = infer_semantic_completeness(case, "C")["semantic_inferred"]
    assert inferred["source_evidence_id"] == "A:histology"
    case = case_with_events(
        ("A", "pathology", {"pathology_confirmed": False, "supersedes_event_id": "B"}),
        ("B", "pathology", {"pathology_confirmed": True, "supersedes_event_id": "A"}),
    )
    assert review(case, "B")["final_decision"] == "DEFER_DECISION"


@pytest.mark.parametrize("corrected", [False, True])
def test_conflicting_agent_claims_require_two_effective_records(corrected):
    # This field is outside the source-conflict allowlist. Only the two
    # specialists' validated citations can trigger a structured disagreement.
    replacement = {"review_flag": 1, "pathology_confirmed": True}
    if corrected:
        replacement["supersedes_event_id"] = "A"
    case = case_with_events(
        ("A", "pathology", {"review_flag": True}),
        ("B", "pathology", replacement),
    )
    request = RunRequest(case_id=case.case_id, case_version=case.version, trigger_event_id="B", mode="llm")

    def reviewer(context):
        role = context["agent_id"]
        source_event = "A" if role == "oncology" else "B"
        ref = next(ref for ref in context["evidence_registry"] if ref["evidence_id"] == f"{source_event}:review_flag")
        return {
            "agent_id": role, "decision": "READY_FOR_REVIEW", "summary": "核对引用记录。",
            "evidence_ids": [ref["evidence_id"]],
            "claims": [{key: ref[key] for key in ("evidence_id", "fact_key", "value")}],
            "missing_information": [], "confidence": "high",
            "model_info": {"provider": "fixture", "model": "offline", "prompt_version": "test", "attempts": 1},
        }

    report = execute(case, request, "run_same_day", lambda *args: None, lambda: False, llm=reviewer)
    assert report["status"] == "completed"
    assert report["initial_opinions"][0]["evidence_ids"] == ["A:review_flag"]
    if corrected:
        assert report["final_decision"] == "READY_FOR_REVIEW"
        assert report["discussion_rounds"] == 0 and not report["unresolved_conflicts"]
    else:
        assert report["final_decision"] == "DEFER_DECISION"
        assert report["discussion_rounds"] == 1
        conflict, = report["unresolved_conflicts"]
        assert conflict["dimension"] == "structured_fact_difference"
        assert conflict["evidence_ids"] == ["A:review_flag", "B:review_flag"]


def test_cross_specialty_comparisons_require_measured_pairs():
    case = case_with_events(("A", "observation", {"observation_reviewed": True}))
    report = review(case, "A")
    metrics = compute_run_consensus_metrics(report)
    assert metrics["converged"] is metrics["claim_agreement_rate"] is metrics["evidence_jaccard_mean"] is None
    assert metrics["evidence_pair_count"] == metrics["comparable_claim_pairs"] == 0
    report["final_opinions"].append({
        **report["final_opinions"][0], "agent_id": "radiology", "evidence_ids": ["B:other"],
        "claims": [{"fact_key": "other", "value": True, "evidence_id": "B:other"}],
    })
    metrics = compute_run_consensus_metrics(report)
    assert metrics["evidence_pair_count"] == 1 and metrics["evidence_jaccard_mean"] == 0
    assert metrics["comparable_claim_pairs"] == 0 and metrics["claim_agreement_rate"] is None
