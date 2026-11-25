import json
import time

import pytest
from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from mdt_demo.research.consensus_metrics import compute_specialist_utilities
from mdt_demo.research.datasets import prepare_import
from mdt_demo.research.engine import execute, route_case, source_conflicts
from mdt_demo.research.schemas import ResearchCase, RunRequest
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.store import TERMINAL


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as test_client:
        yield test_client


def _finish(client: TestClient, run_id: str) -> dict:
    for _ in range(600):
        snap = client.get(f"/api/v2/runs/{run_id}").json()["data"]
        if snap["status"] in TERMINAL:
            return snap
        time.sleep(0.005)
    pytest.fail("Run did not terminate in time")


def test_adaptive_routing_escalates_on_domain_deficit_and_imaging_staleness():
    # Domain deficit escalation: LUNG-SYN-002 E003 (molecular_test) has prior imaging_complete=False
    case2 = seed_cases()[1]
    assert route_case(case2, "E003", "event")["selected_agents"] == ["oncology", "pathology"]
    adaptive_route = route_case(case2, "E003", "adaptive")
    assert adaptive_route["selected_agents"] == ["oncology", "radiology", "pathology"]
    assert adaptive_route["strategy_version"] == "adaptive-utility-router-v1"

    # Temporal staleness escalation: >60 days without imaging on a treatment trigger recruits radiology
    stale_case = ResearchCase.model_validate({
        "case_id": "STALE-001",
        "title": "右肺腺癌随访复核（人工构造）",
        "disease": "肺腺癌（人工构造）",
        "case_kind": "synthetic",
        "version": 1,
        "patient": {"age": 61, "sex": "female"},
        "current_question": "评估治疗期影像时效性。",
        "provenance": [{
            "source_name": "research_scenario_generator",
            "source_url": None,
            "dataset_version": "test-v1",
            "license": "合成测试",
            "synthetic": True,
        }],
        "timeline": [
            {
                "event_id": "E001",
                "occurred_at": "2026-01-01",
                "event_type": "diagnosis",
                "title": "初诊影像病理建档",
                "facts": {"imaging_complete": True, "pathology_confirmed": True, "molecular_complete": True},
                "source": "research_scenario_generator",
                "source_record_id": None,
                "synthetic_extension": True,
                "confidence": "synthetic",
                "introduced_in_version": 1,
            },
            {
                "event_id": "E002",
                "occurred_at": "2026-04-10",
                "event_type": "treatment",
                "title": "治疗阶段评估（距前次影像 99 天）",
                "facts": {"treatment_record_complete": True, "pathology_confirmed": True},
                "source": "research_scenario_generator",
                "source_record_id": None,
                "synthetic_extension": True,
                "confidence": "synthetic",
                "introduced_in_version": 1,
            },
        ],
    })
    assert route_case(stale_case, "E002", "event")["selected_agents"] == ["oncology"]
    stale_adaptive = route_case(stale_case, "E002", "adaptive")
    assert stale_adaptive["selected_agents"] == ["oncology", "radiology"]
    util = compute_specialist_utilities(stale_case)
    assert util["imaging_staleness_days"] == 99


def test_source_conflicts_detects_opposing_biomarker_facts():
    case = ResearchCase.model_validate({
        "case_id": "BIO-CONF-001",
        "title": "左肺腺癌双份基因检测对照（人工构造）",
        "disease": "肺腺癌",
        "case_kind": "synthetic",
        "version": 1,
        "patient": {"age": 59, "sex": "male"},
        "current_question": "核查同日分子检测分歧。",
        "provenance": [{
            "source_name": "research_scenario_generator",
            "source_url": None,
            "dataset_version": "test-v1",
            "license": "合成测试",
            "synthetic": True,
        }],
        "timeline": [
            {
                "event_id": "E001",
                "occurred_at": "2026-05-01",
                "event_type": "molecular_test",
                "title": "分子检测记录 A",
                "facts": {"pathology_confirmed": True, "molecular_complete": True, "egfr_status": "Mutant"},
                "source": "research_scenario_generator",
                "source_record_id": None,
                "synthetic_extension": True,
                "confidence": "synthetic",
                "introduced_in_version": 1,
            },
            {
                "event_id": "E002",
                "occurred_at": "2026-05-01",
                "event_type": "molecular_test",
                "title": "分子检测记录 B",
                "facts": {"pathology_confirmed": True, "molecular_complete": True, "egfr_status": "Wildtype"},
                "source": "research_scenario_generator",
                "source_record_id": None,
                "synthetic_extension": True,
                "confidence": "synthetic",
                "introduced_in_version": 1,
            },
        ],
    })
    detected = source_conflicts(case, ["oncology", "pathology"])
    assert any(item["conflict_id"] == "source_egfr_status" for item in detected)
    report = execute(
        case,
        RunRequest(case_id=case.case_id, case_version=1, trigger_event_id="E002", routing_mode="adaptive"),
        "run_bio_conflict",
        lambda *args: None,
        lambda: False,
    )
    assert report["final_decision"] == "DEFER_DECISION"
    assert report["safety"]["status"] == "blocked"


def test_consensus_metrics_and_longitudinal_dynamics_endpoints(client):
    # Routing endpoint supports adaptive mode
    routing_res = client.get("/api/v2/cases/LUNG-SYN-002/routing?trigger_event_id=E003&routing_mode=adaptive")
    assert routing_res.status_code == 200
    assert routing_res.json()["data"]["selected_agents"] == ["oncology", "radiology", "pathology"]

    # Run LUNG-SYN-001 E001 (initial disagreement resolves after discussion round)
    run_id = client.post("/api/v2/runs", json={
        "case_id": "LUNG-SYN-001", "case_version": 1, "trigger_event_id": "E001", "routing_mode": "adaptive",
    }).json()["data"]["run_id"]
    _finish(client, run_id)
    metrics_res = client.get(f"/api/v2/runs/{run_id}/consensus-metrics")
    assert metrics_res.status_code == 200
    metrics = metrics_res.json()["data"]
    assert metrics["routing_mode"] == "adaptive"
    assert metrics["initial_entropy"] > metrics["final_entropy"] == 0.0
    assert metrics["entropy_reduction"] > 0
    assert metrics["converged"] is True
    assert metrics["opinions_revised_count"] == 1
    assert metrics["consensus_score"] > 0

    # Run LUNG-SYN-003 E004 (unresolved conflict triggers veto -> consensus_score == 0)
    conflict_run = client.post("/api/v2/runs", json={
        "case_id": "LUNG-SYN-003", "case_version": 1, "trigger_event_id": "E004", "routing_mode": "event",
    }).json()["data"]["run_id"]
    _finish(client, conflict_run)
    conflict_metrics = client.get(f"/api/v2/runs/{conflict_run}/consensus-metrics").json()["data"]
    assert conflict_metrics["consensus_score"] == 0.0
    assert conflict_metrics["safety_veto_applied"] is True

    # Longitudinal dynamics endpoint across all checkpoints of LUNG-SYN-001
    dyn_res = client.get("/api/v2/cases/LUNG-SYN-001/longitudinal-dynamics")
    assert dyn_res.status_code == 200
    dyn = dyn_res.json()["data"]
    assert dyn["checkpoint_count"] == 6
    assert dyn["first_ready_event_id"] == "E003"
    assert dyn["cumulative_calls"]["event"] < dyn["cumulative_calls"]["fixed"]


def test_clinical_case_titles_and_tcia_non_leakage():
    seeds = seed_cases()
    assert not seeds[0].title.startswith("资料逐步补齐")
    assert "占位" in seeds[0].title

    csv_raw = (
        "Case ID,Age at Histological Diagnosis,Gender,CT Date,PET Date,Histology\n"
        "R01-0001,60,Female,01/15/2018,01/20/2018,Adenocarcinoma\n"
    ).encode("utf-8")
    prepared = prepare_import("tcia_nsclc_csv", csv_raw, 5)
    tcia_case = ResearchCase.model_validate(prepared.cases[0])
    assert "60岁女性" in tcia_case.title
    assert "CT / PET" in tcia_case.title
    assert "Adenocarcinoma" not in tcia_case.title
    assert "Adenocarcinoma" not in json.dumps(tcia_case.model_dump(mode="json")["timeline"], ensure_ascii=False)
