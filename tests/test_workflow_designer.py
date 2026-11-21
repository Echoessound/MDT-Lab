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
from test_dataset_import import finish, preview, commit, tcia_bytes


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        yield client


def test_imaging_pipeline_extracts_radiomics_and_detects_missing_or_conflicting_studies():
    cases = {c.case_id: c for c in seed_cases()}

    # Standard case with valid imaging at E002
    img1 = process_case_imaging(cases["LUNG-SYN-001"], "E002")
    assert img1["study_count"] == 1
    assert img1["overall_qc_status"] == "passed"
    study = img1["studies"][0]
    assert study["modality"] == "CT"
    assert study["radiomics"]["lesion_diameter_mm"] > 0
    assert len(study["pipeline_steps"]) == 4
    assert study["svg_slice"]["contour_polygon"]

    # Missing imaging attachment in LUNG-SYN-002
    img2 = process_case_imaging(cases["LUNG-SYN-002"], "E002")
    assert img2["overall_qc_status"] == "warning"
    assert img2["studies"][0]["qc_status"] == "incomplete"

    # Same-day conflicting imaging in LUNG-SYN-003
    img3 = process_case_imaging(cases["LUNG-SYN-003"], "E004")
    assert img3["overall_qc_status"] == "conflict"
    assert any(s["qc_status"] == "conflict" for s in img3["studies"])


def test_workflow_designer_and_semantic_inference_bridge_external_tcia_dataset():
    prepared = prepare_import("tcia_nsclc_csv", tcia_bytes(("R01-001",), histology="Adenocarcinoma"))
    tcia_case = ResearchCase.model_validate(prepared.cases[0])
    first_event_id = tcia_case.timeline[0].event_id

    completeness = infer_semantic_completeness(tcia_case, first_event_id)
    assert "imaging_complete" in completeness["strict_missing"]
    assert "pathology_confirmed" in completeness["strict_missing"]
    assert completeness["strict_completeness_score"] == 0
    assert completeness["semantic_completeness_score"] == 100
    assert completeness["can_auto_enrich"] is True
    assert completeness["recommended_facts"]["imaging_complete"] is True
    assert completeness["recommended_facts"]["pathology_confirmed"] is True

    plan = design_medical_workflow(tcia_case, first_event_id)
    assert plan["strategy_version"] == "case-adaptive-workflow-v2"
    assert len(plan["workflow_stages"]) == 6
    assert plan["predicted_decisions"]["strict_rule_decision"] == "NEED_MORE_INFORMATION"
    assert plan["predicted_decisions"]["semantic_enriched_decision"] == "READY_FOR_REVIEW"


def test_ablation_matrix_evaluates_b0_to_b3_and_single_factor_ablations():
    case = seed_cases()[0]
    matrix = evaluate_ablation_matrix(case, "E003")
    methods = {m["method_id"]: m for m in matrix["methods"]}
    assert set(methods) == {"B0", "B1", "B2", "B3", "A1", "A2"}
    assert methods["B0"]["agent_calls"] == 1
    assert methods["B1"]["agent_calls"] == 4
    assert methods["B3"]["agent_calls"] == 2
    assert matrix["call_saving_pct"] == 50
    # At E003, full longitudinal memory has imaging + pathology, whereas A1 (trigger-only) only sees E003
    assert methods["B3"]["final_decision"] == "READY_FOR_REVIEW"


def test_api_workflow_imaging_ablation_and_auto_enrich_end_to_end(client):
    # 1. Import a public TCIA case
    item = preview(client, tcia_bytes(("T888",), histology="Adenocarcinoma"))
    batch = commit(client, item).json()["data"]
    case_id = batch["imported_case_ids"][0]
    v1_case = client.get(f"/api/v2/cases/{case_id}").json()["data"]
    trigger_id = v1_case["timeline"][0]["event_id"]

    # 2. Query workflow plan, imaging pipeline, and ablation matrix
    wf_res = client.get(f"/api/v2/cases/{case_id}/workflow-plan?trigger_event_id={trigger_id}")
    assert wf_res.status_code == 200
    assert wf_res.json()["data"]["completeness"]["can_auto_enrich"] is True

    img_res = client.get(f"/api/v2/cases/{case_id}/imaging?trigger_event_id={trigger_id}")
    assert img_res.status_code == 200
    assert img_res.json()["data"]["study_count"] == 1

    abl_res = client.get(f"/api/v2/cases/{case_id}/ablation?trigger_event_id={trigger_id}")
    assert abl_res.status_code == 200
    methods = {m["method_id"]: m for m in abl_res.json()["data"]["methods"]}
    assert methods["B3"]["final_decision"] == "NEED_MORE_INFORMATION"
    assert methods["A2"]["final_decision"] == "READY_FOR_REVIEW"

    # 3. Auto-enrich case into v2 and verify full MDT run reaches READY_FOR_REVIEW
    enrich_res = client.post(
        f"/api/v2/cases/{case_id}/auto-enrich",
        json={"expected_version": 1, "trigger_event_id": trigger_id},
    )
    assert enrich_res.status_code == 201
    v2_case = enrich_res.json()["data"]
    assert v2_case["version"] == 2
    assert v2_case["case_kind"] == "mixed"
    new_event_id = v2_case["timeline"][-1]["event_id"]

    run_res = client.post(
        "/api/v2/runs",
        json={"case_id": case_id, "case_version": 2, "trigger_event_id": new_event_id},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["data"]["run_id"]
    finish(client, run_id)
    report = client.get(f"/api/v2/runs/{run_id}/report").json()["data"]
    assert report["final_decision"] == "READY_FOR_REVIEW"
    # v1 remains strictly untouched
    assert client.get(f"/api/v2/cases/{case_id}?version=1").json()["data"]["case_kind"] == "public_research"
