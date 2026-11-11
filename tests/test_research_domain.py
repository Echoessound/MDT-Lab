from copy import deepcopy

import pytest

from mdt_demo.research.engine import (
    WorkflowCancelled, detect_conflicts, evidence_registry, execute,
    freeze_context, route_case, validate_output, WorkflowError,
)
from mdt_demo.research.schemas import ResearchCase, RunRequest
from mdt_demo.research.seeds import seed_cases


def run(case=None, trigger="E002", **options):
    case = case or seed_cases()[0]
    events = []
    report = execute(case, RunRequest(case_id=case.case_id, case_version=case.version,
                                     trigger_event_id=trigger, **options), "run_domain_test",
                     lambda *event: events.append(event), lambda: False)
    return report, events


def test_historical_event_never_sees_future_facts():
    case = seed_cases()[0]
    report, _ = run(case, "E002")
    assert [event["event_id"] for event in report["case_snapshot"]["timeline"]] == ["E001", "E002"]
    assert "pathology_confirmed" in report["safety"]["missing_information"]
    assert not any(evidence["event_id"] == "E003" for evidence in report["evidence_registry"])
    assert run(case, "E003")[0]["final_decision"] == "READY_FOR_REVIEW"
    assert len(case.timeline) == 6


def test_event_router_changes_real_participants_and_dynamic_denominator():
    case = seed_cases()[0]
    assert route_case(case, "E002")["selected_agents"] == ["oncology", "radiology"]
    assert route_case(case, "E003")["selected_agents"] == ["oncology", "pathology"]
    dynamic, _ = run(case, "E003")
    fixed, _ = run(case, "E003", routing_mode="fixed")
    assert dynamic["metrics"]["agent_calls"] == 2 and fixed["metrics"]["agent_calls"] == 4
    assert dynamic["final_decision"] == fixed["final_decision"] == "READY_FOR_REVIEW"
    assert dynamic["metrics"]["prompt_tokens"] is None


@pytest.mark.parametrize("scenario,status", [("partial_failure", "incomplete"), ("invalid_evidence", "incomplete"), ("persistent_disagreement", "completed")])
def test_failures_and_retained_disagreement_never_force_consensus(scenario, status):
    report, events = run(mock_scenario=scenario)
    assert report["status"] == status
    assert report["final_decision"] == "DEFER_DECISION"
    assert report["safety"]["status"] == "blocked"
    assert report["discussion_rounds"] <= 1
    if scenario == "invalid_evidence":
        assert any(event[0] == "agent.failed" and event[2]["error_code"] == "invalid_evidence" for event in events)


def test_all_agents_agreeing_cannot_erase_source_conflict():
    report, _ = run(seed_cases()[2], "E004")
    assert len({opinion["decision"] for opinion in report["final_opinions"]}) == 1
    assert report["unresolved_conflicts"]
    assert report["unresolved_conflicts"][0]["dimension"] == "source_fact_conflict"
    assert report["final_decision"] == "DEFER_DECISION"


def test_equal_labels_can_still_have_structured_fact_conflict():
    opinions = [{"agent_id": "oncology", "decision": "NEED_MORE_INFORMATION", "claims": [{"fact_key": "x", "value": False, "evidence_id": "E1:x"}]},
                {"agent_id": "radiology", "decision": "NEED_MORE_INFORMATION", "claims": [{"fact_key": "x", "value": True, "evidence_id": "E2:x"}]}]
    assert detect_conflicts(opinions, [])[0]["dimension"] == "structured_fact_difference"


def test_references_are_validated_against_frozen_registry():
    report, _ = run()
    opinion = deepcopy(report["initial_opinions"][0])
    opinion.pop("opinion_id"); opinion.pop("evidence_refs")
    opinion["evidence_ids"] = ["E003:pathology_confirmed"]
    opinion["claims"] = [{"evidence_id": "E003:pathology_confirmed", "fact_key": "pathology_confirmed", "value": True}]
    with pytest.raises(WorkflowError, match="invalid_evidence"):
        validate_output(opinion, "oncology", report["evidence_registry"], "op_invalid")


def test_discussion_is_bounded_and_peers_are_isolated():
    report, events = run()
    assert report["discussion_rounds"] == 1 and len(report["discussion_records"]) == 2
    for role in report["routing"]["selected_agents"]:
        calls = [event for event in events if event[0] == "agent.started" and event[3] == role]
        assert [event[2]["phase"] for event in calls] == ["initial", "discussion"]
    assert report["initial_opinions"][1]["decision"] == "READY_FOR_REVIEW"
    assert report["final_opinions"][1]["decision"] == "NEED_MORE_INFORMATION"


def test_cancellation_stops_before_any_agent_call():
    case = seed_cases()[0]
    with pytest.raises(WorkflowCancelled):
        execute(case, RunRequest(case_id=case.case_id, case_version=1, trigger_event_id="E002"), "run_cancel", lambda *args: None, lambda: True)


def test_same_day_explicit_supersession_resolves_source_conflict():
    case = seed_cases()[2]
    payload = case.model_dump(mode="json")
    payload["timeline"][2]["facts"]["supersedes_event_id"] = "E002"
    revised = ResearchCase.model_validate(payload)
    report, _ = run(revised, "E004")
    assert not report["unresolved_conflicts"]


def test_registry_contains_server_created_provenance():
    case = freeze_context(seed_cases()[0], "E002")
    registry = evidence_registry(case)
    assert all(item["synthetic"] is True and item["source_name"] == "research_scenario_generator" for item in registry)
    assert all(item["dataset_version"] == "lung-scenarios-v1" for item in registry)
