from fastapi.testclient import TestClient
import pytest

from mdt_demo.api import create_app
from mdt_demo.research.datasets import prepare_import
from mdt_demo.research.schemas import ResearchCase
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.workflow_designer import (
    design_medical_workflow,
    evaluate_ablation_matrix,
    infer_semantic_completeness,
    process_case_imaging,
)
from test_dataset_import import finish, preview, commit, synthea_bytes, tcia_bytes


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        yield client


def test_imaging_records_keep_pixel_results_unavailable_and_scope_source_conflicts():
    complete, missing, conflicting = seed_cases()
    assert process_case_imaging(complete, "E001")["studies"] == []
    image = process_case_imaging(complete, "E002")
    assert image["study_count"] == 1 and image["overall_qc_status"] == "not_assessed"
    study = image["studies"][0]
    assert study["synthetic"] and study["record_status"] == "documented"
    assert study["modality"] is None and study["anatomical_site"] is None
    assert study["qc_status"] == "not_assessed"
    assert all(study[key] is None for key in ("qc_score", "dicom_metadata", "radiomics", "svg_slice"))

    assert process_case_imaging(missing, "E002")["overall_record_status"] == "incomplete"
    assert process_case_imaging(conflicting, "E002")["overall_record_status"] == "documented"
    reviewed = process_case_imaging(conflicting, "E004")
    assert reviewed["overall_record_status"] == "conflict"
    assert all(study["conflict_evidence_ids"] == ["E002:progression_confirmed", "E003:progression_confirmed"]
               for study in reviewed["studies"])


def test_tcia_imaging_preserves_modality_source_and_time_boundary():
    imported = prepare_import("tcia_nsclc_csv", tcia_bytes())
    case = ResearchCase.model_validate(imported.cases[0])
    ct_event, pet_event = case.timeline
    image = process_case_imaging(case, ct_event.event_id)
    assert image["input_kind"] == "event_metadata"
    assert [item["event_id"] for item in image["studies"]] == [ct_event.event_id]
    ct = image["studies"][0]
    assert ct["modality"] == "CT" and ct["anatomical_site"] is None
    assert not ct["synthetic"] and ct["artifact_sha256"] == case.provenance[0].artifact_sha256
    assert ct["source_record_locator"] == ct_event.source_record_locator
    assert {"fact_key": "modality", "value": "CT", "source_field": "CT Date",
            "evidence_id": f"{ct_event.event_id}:modality"} in ct["record_fields"]
    pet = process_case_imaging(case, pet_event.event_id)["studies"][-1]
    assert pet["modality"] == "PET" and pet["radiomics"] is None and pet["dicom_metadata"] is None


def test_synthea_imaging_preserves_non_ct_modality_and_anatomy():
    raw = synthea_bytes(("csv/imaging_studies.csv",
                         "PATIENT,DATE,MODALITY_CODE,BODYSITE_DESCRIPTION\nP001,2000-01-03,MR,Knee\n"))
    case = ResearchCase.model_validate(prepare_import("synthea_csv", raw).cases[0])
    study, = process_case_imaging(case)["studies"]
    assert (study["modality"], study["anatomical_site"], study["synthetic"]) == ("MR", "Knee", True)
    assert study["qc_status"] == "not_assessed" and study["radiomics"] is None
    assert {field["source_field"] for field in study["record_fields"]} == {"MODALITY_CODE", "BODYSITE_DESCRIPTION"}


def test_public_imaging_registration_and_unplaced_histology_cannot_fill_missing_information():
    imported = prepare_import("tcia_nsclc_csv", tcia_bytes(("R01-001",)))
    case = ResearchCase.model_validate(imported.cases[0])
    trigger_id = case.timeline[0].event_id
    completeness = infer_semantic_completeness(case, trigger_id)
    assert completeness["strict_missing"] == completeness["post_inference_missing"] == [
        "imaging_complete", "pathology_confirmed",
    ]
    assert completeness["strict_completeness_score"] == completeness["semantic_completeness_score"] == 0
    assert completeness["recommended_facts"] == {}
    assert not completeness["can_auto_enrich"]
    assert "Adenocarcinoma" not in str(completeness)
    plan = design_medical_workflow(case, trigger_id)
    assert set(plan["predicted_decisions"].values()) == {"NEED_MORE_INFORMATION"}


@pytest.mark.parametrize(("event_type", "facts"), [
    ("diagnosis", {"code": "123", "description": "histology pending"}),
    ("pathology", {"histology": "possible adenocarcinoma"}),
    ("pathology", {"histology": "Adenocarcinoma", "pathology_confirmed": False}),
    ("pathology", {"histology": "Adenocarcinoma", "histology_missing_reason": "未核验"}),
    ("molecular_test", {"egfr_status": None}),
    ("follow_up", {"recorded_date": "2000-01-01"}),
])
def test_semantic_rules_reject_insufficient_or_explicitly_negative_evidence(event_type, facts):
    data = seed_cases()[0].model_dump(mode="json")
    data["timeline"] = [{**data["timeline"][0], "event_type": event_type, "facts": facts}]
    result = infer_semantic_completeness(ResearchCase.model_validate(data))
    assert not result["can_auto_enrich"]
    assert result["recommended_facts"] == {}


def test_conflicting_dated_histologies_are_not_enriched():
    data = seed_cases()[0].model_dump(mode="json")
    first = {**data["timeline"][0], "event_type": "pathology", "facts": {"histology": "Adenocarcinoma"}}
    data["timeline"] = [first, {**first, "event_id": "E002", "facts": {"histology": "Squamous cell carcinoma"}}]
    case = ResearchCase.model_validate(data)
    assert infer_semantic_completeness(case, "E001")["can_auto_enrich"]
    assert not infer_semantic_completeness(case, "E002")["can_auto_enrich"]


def test_superseded_and_undated_results_never_replace_the_current_record():
    data = seed_cases()[0].model_dump(mode="json")
    latest = {**data["timeline"][0], "event_id": "E002", "event_type": "pathology",
              "facts": {"histology": "Adenocarcinoma"}}
    correction = {**latest, "event_id": "E001", "facts": {"histology": "pending", "supersedes_event_id": "E002"}}
    data["timeline"] = [correction, latest]
    assert not infer_semantic_completeness(ResearchCase.model_validate(data))["can_auto_enrich"]
    data["timeline"] = [latest, {**latest, "event_id": "E003", "facts": {"histology_missing_reason": "撤回结论"}}]
    assert not infer_semantic_completeness(ResearchCase.model_validate(data))["can_auto_enrich"]


@pytest.mark.parametrize(("target_id", "other_id", "other_date", "expected_id"), [
    ("E1", "E1-", "2026-01-05", None),
    ("E1", "E1-", "2026-01-06", "E1--"),
    ("E1", "E10", "2026-01-05", "E1-"),
    ("a" * 79 + "z", "b", "2026-01-05", "a" * 78 + "b"),
    ("z" * 80, "E001", "2026-01-05", None),
])
def test_enrichment_allocates_an_adjacent_cutoff_or_declines(target_id, other_id, other_date, expected_id):
    data = seed_cases()[0].model_dump(mode="json")
    anchor = {**data["timeline"][0], "event_id": target_id, "event_type": "pathology",
              "facts": {"histology": "Adenocarcinoma"}}
    data["timeline"] = [anchor, {**anchor, "event_id": other_id, "occurred_at": other_date, "facts": {"note": "another event"}}]
    result = infer_semantic_completeness(ResearchCase.model_validate(data), target_id)
    assert result["extension_event_id"] == expected_id
    assert result["can_auto_enrich"] == (expected_id is not None)


def test_ablation_matrix_uses_real_mock_trajectories_and_a_paired_gate_readout(monkeypatch):
    from collections import defaultdict
    from mdt_demo.research import engine

    calls = defaultdict(list)
    original = engine._mock

    def record_call(context, *args):
        calls[context["run_id"]].append((context["agent_id"], context["phase"]))
        return original(context, *args)

    monkeypatch.setattr(engine, "_mock", record_call)
    case = seed_cases()[0]
    matrix = evaluate_ablation_matrix(case, "E002")
    methods = {m["method_id"]: m for m in matrix["methods"]}
    assert matrix["execution_mode"] == "mock"
    assert set(methods) == {"B0", "B1", "B2", "B3", "A1", "A2", "A3", "A4"}
    assert calls["B0"] == [("general_reviewer", "initial")]
    assert len(calls["B1"]) == 4 and all(phase == "initial" for _, phase in calls["B1"])
    assert calls["B3"] == [("oncology", "initial"), ("radiology", "initial"),
                           ("oncology", "discussion"), ("radiology", "discussion")]
    assert calls["A4"] == calls["B3"][:2]
    assert methods["B2"]["trajectory_id"] == methods["B3"]["trajectory_id"] == "B3"
    assert methods["B2"]["final_decision"] == methods["B3"]["pre_gate_decision"]
    assert methods["A4"]["pre_gate_decision"] == methods["A4"]["final_decision"] == "DEFER_DECISION"
    assert methods["A4"]["unresolved_conflicts"] == 1
    assert methods["B3"]["final_decision"] == "NEED_MORE_INFORMATION"
    assert methods["B3"]["unresolved_conflicts"] == 0
    assert matrix["fixed_total_calls"] == methods["A3"]["agent_calls"] == 8
    assert matrix["routed_total_calls"] == methods["B3"]["agent_calls"] == 4
    assert matrix["call_saving_pct"] == 50
    for method in methods.values():
        assert method["agent_calls"] == len(calls[method["trajectory_id"]])


def test_memory_ablation_rebuilds_missing_fields_for_the_trigger_only():
    matrix = evaluate_ablation_matrix(seed_cases()[0], "E006")
    rows = {method["method_id"]: method for method in matrix["methods"]}
    assert rows["A1"]["visible_events"] == 1 and rows["B3"]["visible_events"] == 6
    assert rows["A1"]["final_decision"] == "NEED_MORE_INFORMATION"
    assert rows["A1"]["missing_count"] == 1 and rows["B3"]["missing_count"] == 0
    assert rows["B3"]["final_decision"] == "READY_FOR_REVIEW"


def test_offline_semantic_extension_and_all_method_rows_are_independent_of_later_events():
    payload = seed_cases()[0].model_dump(mode="json")
    anchor = {**payload["timeline"][0], "event_type": "pathology", "facts": {"histology": "Adenocarcinoma"}}
    payload["timeline"] = [anchor]
    matrix = evaluate_ablation_matrix(ResearchCase.model_validate(payload), anchor["event_id"])
    rows = {row["method_id"]: row for row in matrix["methods"]}
    assert rows["B3"]["final_decision"] == "NEED_MORE_INFORMATION"
    assert rows["A2"]["final_decision"] == "READY_FOR_REVIEW"
    assert rows["A2"]["input_case_version"] == 2 and rows["A2"]["visible_events"] == 2
    # Even a later same-day record occupying the projected extension ID stays invisible.
    payload["timeline"].append({
        **anchor, "event_id": rows["A2"]["input_trigger_event_id"], "facts": {"pathology_confirmed": False},
    })
    assert evaluate_ablation_matrix(ResearchCase.model_validate(payload), anchor["event_id"]) == matrix


def test_plurality_with_no_valid_opinions_is_distinct_from_gate_deferral(monkeypatch):
    from mdt_demo.research import engine

    def fail(*args):
        raise engine.WorkflowError("simulated_agent_failure")

    monkeypatch.setattr(engine, "_mock", fail)
    matrix = evaluate_ablation_matrix(seed_cases()[0], "E003")
    rows = {method["method_id"]: method for method in matrix["methods"]}
    for key in ("B0", "B1", "B2"):
        assert rows[key]["final_decision"] is None
    for row in rows.values():
        assert row["pre_gate_decision"] is None and row["valid_opinions"] == 0
        assert row["failed_calls"] == row["agent_calls"]
    assert rows["B3"]["final_decision"] == "DEFER_DECISION"


def test_api_only_writes_traceable_cutoff_bound_facts_in_a_new_version(client):
    batch = commit(client, preview(client, tcia_bytes(("T888",)))).json()["data"]
    case_id = batch["imported_case_ids"][0]
    path = f"/api/v2/cases/{case_id}"
    original = client.get(path).json()["data"]
    trigger = original["timeline"][0]
    trigger_id = trigger["event_id"]
    req = {"trigger_event_id": trigger_id, "expected_version": 1}
    declined = client.post(path + "/auto-enrich", json=req)
    assert declined.status_code == 422
    assert declined.json()["error"]["code"] == "NO_SUPPORTED_ENRICHMENT"
    assert client.get(path).json()["data"] == original
    assert client.post(path + "/auto-enrich", json={**req, "trigger_event_id": "unknown"}).status_code == 404
    raw_matrix = client.get(path + "/ablation", params={"trigger_event_id": trigger_id}).json()["data"]
    rows = {row["method_id"]: row for row in raw_matrix["methods"]}
    assert rows["A2"]["final_decision"] == rows["B3"]["final_decision"] == "NEED_MORE_INFORMATION"

    prior = client.post(path + "/events", json={"expected_version": 1, "event": {
        "occurred_at": "2000-01-01", "event_type": "pathology", "title": "合成的带日期病理报告",
        "facts": {"histology": "Adenocarcinoma"},
    }})
    assert prior.status_code == 201
    source_id = prior.json()["data"]["timeline"][0]["event_id"]
    later = client.post(path + "/events", json={"expected_version": 2, "event": {
        "occurred_at": trigger["occurred_at"], "event_type": "imaging", "title": "同日排序在后的影像核验",
        "facts": {"imaging_complete": True},
    }})
    assert later.status_code == 201
    before = later.json()["data"]
    wf = client.get(path + "/workflow-plan", params={"version": 3, "trigger_event_id": trigger_id})
    completeness = wf.json()["data"]["completeness"]
    assert completeness["recommended_facts"] == {"pathology_confirmed": True}
    assert completeness["post_inference_missing"] == ["imaging_complete"]
    assert completeness["semantic_inferred"][0]["source_evidence_id"] == f"{source_id}:histology"
    assert client.post(path + "/auto-enrich", json=req).status_code == 409

    saved = client.post(path + "/auto-enrich", json={**req, "expected_version": 3})
    assert saved.status_code == 201
    case = saved.json()["data"]
    assert case["version"] == 4 and case["case_kind"] == "mixed"
    added, = [ev for ev in case["timeline"] if ev["introduced_in_version"] == 4]
    assert added["facts"] == {"pathology_confirmed": True}
    assert added["source_fields"] == {"pathology_confirmed": f"{source_id}:histology"}
    assert added["source_record_locator"] == f"{case_id}@v3/{trigger_id}"
    assert added["synthetic_extension"] is True
    assert client.get(path, params={"version": 1}).json()["data"] == original
    assert client.get(path, params={"version": 3}).json()["data"] == before
    assert client.post(path + "/auto-enrich", json={**req, "expected_version": 4}).status_code == 422

    started = client.post("/api/v2/runs", json={
        "case_id": case_id, "case_version": 4, "trigger_event_id": added["event_id"],
    })
    assert started.status_code == 202
    run_id = started.json()["data"]["run_id"]
    finish(client, run_id)
    report = client.get(f"/api/v2/runs/{run_id}/report").json()["data"]
    assert report["final_decision"] == "NEED_MORE_INFORMATION"
    assert [ev["event_id"] for ev in report["case_snapshot"]["timeline"]] == [source_id, trigger_id, added["event_id"]]
    assert report["safety"]["missing_information"] == ["imaging_complete"]
    refs = {ref["evidence_id"]: ref for ref in report["evidence_registry"]}
    assert refs[f"{added['event_id']}:pathology_confirmed"]["source_field"] == f"{source_id}:histology"
