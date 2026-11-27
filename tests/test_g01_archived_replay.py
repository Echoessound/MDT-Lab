"""Replay the recorded DeepSeek first-round outputs without contacting a provider."""

import json
from pathlib import Path

from mdt_demo.research.engine import execute
from mdt_demo.research.schemas import RunRequest
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.temporal_audit import audit_temporal_boundary


def test_archived_initial_opinions_release_complete_case_and_keep_history():
    # The fixture retains the AgentOutput and model_info fields from each
    # initial opinion. execute regenerates the opinion IDs and evidence refs.
    path = Path(__file__).parent / "fixtures" / "g01_deepseek_complete_case_initial.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    case = next(item for item in seed_cases() if item.case_id == fixture["case_id"])
    request = RunRequest(
        case_id=case.case_id, case_version=fixture["case_version"],
        trigger_event_id=fixture["trigger_event_id"], mode="llm",
    )
    opinions = {item["agent_id"]: item for item in fixture["initial_opinions"]}
    calls = []

    def replay(context):
        calls.append((context["agent_id"], context["phase"]))
        return opinions[context["agent_id"]]

    report = execute(case, request, "g01_archived_initial_replay", lambda *args: None, lambda: False, llm=replay)
    assert calls == [("oncology", "initial"), ("pathology", "initial")]
    assert report["status"] == "completed"
    assert report["metrics"]["llm_calls"] == 0
    assert report["conflicts"] == report["unresolved_conflicts"] == []
    assert report["discussion_rounds"] == 0 and report["discussion_records"] == []
    assert fixture["archived_decision"] == "DEFER_DECISION"
    assert report["final_decision"] == "READY_FOR_REVIEW"
    assert report["safety"]["status"] == "passed"

    assert len(report["final_opinions"]) == len(opinions)
    for final in report["final_opinions"]:
        original = opinions[final["agent_id"]]
        assert final["claims"] == original["claims"]
        assert [ref["evidence_id"] for ref in final["evidence_refs"]] == original["evidence_ids"]
    historical_changes = {
        "E001:imaging_complete", "E002:imaging_complete",
        "E001:pathology_confirmed", "E003:pathology_confirmed",
    }
    assert historical_changes <= set(opinions["oncology"]["evidence_ids"])
    audit = audit_temporal_boundary(case, report)
    assert audit["passed"] and audit["leaked_count"] == 0
