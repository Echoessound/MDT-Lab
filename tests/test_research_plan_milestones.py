"""Tests for Plan G01–G07 milestones: multi-rater blind review & Cohen's kappa,
independent temporal boundary audit, first-attempt LLM telemetry & G01 smoke suite,
family-stratified dev/test split, Macro-F1 / error attribution, and §6.4 repro pack."""

from __future__ import annotations

import csv
import hashlib
import io
import json

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest

from mdt_demo.api import create_app
from mdt_demo.research.adjudication import compute_agreement_report
from mdt_demo.research.cohort_split import build_dataset_and_scenario_manifests, split_by_case_family
from mdt_demo.research.engine import execute
from mdt_demo.research.evaluation import evaluate_library
from mdt_demo.research.experiments import load_annotations_file
from mdt_demo.research.llm_benchmark import evaluate_llm_ablation_matrix, run_g01_smoke_suite
from mdt_demo.research.provider import RunLLM
from mdt_demo.research.provider_config import LLMConfigInput
from mdt_demo.research.schemas import RunRequest
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.temporal_audit import audit_temporal_boundary
from test_dataset_import import tcia_bytes


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as session:
        yield session


def _public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


def _make_llm_config() -> LLMConfigInput:
    return LLMConfigInput(
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        model="gpt-test-mdt",
        api_key=SecretStr("sk-secret-do-not-leak-123456"),
        timeout_seconds=10.0,
        temperature=0.0,
        max_output_tokens=600,
    )


def _smart_llm_transport(*, fail_first_citation: bool = False):
    """Simulate an OpenAI-compatible model endpoint that obeys context or injects one first-attempt bad ref."""
    injected = {"done": False}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        messages = body["messages"]
        user_content = messages[-1]["content"]
        # Connection test
        if "connection test" in user_content:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps({"ok": True})}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            })
        # Find original context message (second message after system)
        ctx = json.loads(messages[1]["content"])
        role = ctx["agent_id"]
        registry = ctx["evidence_registry"]
        first_ref = registry[-1]
        missing = ctx["missing_information"]
        has_conflict = any(c["dimension"] == "source_fact_conflict" for c in ctx["conflicts"])
        decision = "DEFER_DECISION" if has_conflict else "NEED_MORE_INFORMATION" if missing else "READY_FOR_REVIEW"

        if fail_first_citation and not injected["done"] and len(messages) == 2:
            injected["done"] = True
            bad_payload = {
                "agent_id": role,
                "decision": decision,
                "summary": "首次输出含一条越界引用用于验证脱敏计数与重试恢复。",
                "evidence_ids": [first_ref["evidence_id"], "FAKE_EVENT:nonexistent"],
                "claims": [{"fact_key": first_ref["fact_key"], "value": first_ref["value"], "evidence_id": first_ref["evidence_id"]}],
                "missing_information": missing if decision != "READY_FOR_REVIEW" else [],
                "confidence": "medium",
            }
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps(bad_payload, ensure_ascii=False)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            })

        good_payload = {
            "agent_id": role,
            "decision": decision,
            "summary": f"{role} 依据冻结证据完成结构化审阅。",
            "evidence_ids": [first_ref["evidence_id"]],
            "claims": [{"fact_key": first_ref["fact_key"], "value": first_ref["value"], "evidence_id": first_ref["evidence_id"]}],
            "missing_information": missing if decision != "READY_FOR_REVIEW" else [],
            "confidence": "high",
        }
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(good_payload, ensure_ascii=False)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 45},
        })

    return httpx.MockTransport(handler)


def test_multi_rater_blind_review_kappa_adjudication_and_gold_scoring(client, tmp_path):
    s1 = ("LUNG-SYN-001", 1, "E003")
    s2 = ("LUNG-SYN-002", 1, "E003")
    sid1 = "LUNG-SYN-001:v1:E003"
    sid2 = "LUNG-SYN-002:v1:E003"

    m1 = client.get("/api/v2/annotations/material", params={"case_id": s1[0], "version": 1, "trigger_event_id": s1[2]}).json()["data"]
    m2 = client.get("/api/v2/annotations/material", params={"case_id": s2[0], "version": 1, "trigger_event_id": s2[2]}).json()["data"]
    m2_ev = f"{m2['events'][-1]['event_id']}:{next(iter(m2['events'][-1]['facts']))}"

    # Two independent annotators agree on s1, disagree on s2
    p1_a = {
        "case_id": s1[0], "case_version": 1, "trigger_event_id": s1[2],
        "annotator_id": "rater_1", "required_agents": ["oncology", "pathology"],
        "expected_decision": "READY_FOR_REVIEW", "input_sha256": m1["input_sha256"],
        "evidence_ids": ["E003:pathology_confirmed"], "missing_fields": [],
    }
    p1_b = {**p1_a, "annotator_id": "rater_2"}
    p2_a = {
        "case_id": s2[0], "case_version": 1, "trigger_event_id": s2[2],
        "annotator_id": "rater_1", "required_agents": ["oncology", "pathology"],
        "expected_decision": "NEED_MORE_INFORMATION", "input_sha256": m2["input_sha256"],
        "evidence_ids": [m2_ev], "missing_fields": ["pathology_confirmed"],
    }
    p2_b = {
        **p2_a, "annotator_id": "rater_2",
        "required_agents": ["oncology", "radiology"],
        "expected_decision": "DEFER_DECISION",
        "missing_fields": ["imaging_complete"],
    }
    assert client.put(f"/api/v2/review-panel/submissions/{sid1}", json=p1_a).status_code == 200
    assert client.put(f"/api/v2/review-panel/submissions/{sid1}", json=p1_b).status_code == 200
    assert client.put(f"/api/v2/review-panel/submissions/{sid2}", json=p2_a).status_code == 200
    assert client.put(f"/api/v2/review-panel/submissions/{sid2}", json=p2_b).status_code == 200

    # Blind isolation: rater_1 only sees rater_1's own record
    own = client.get("/api/v2/review-panel/own", params={"scenario_id": sid2, "annotator_id": "rater_1"}).json()["data"]
    assert own["annotator_id"] == "rater_1" and own["expected_decision"] == "NEED_MORE_INFORMATION"
    tasks = client.get("/api/v2/review-panel/tasks", params={"annotator_id": "rater_1"}).json()["data"]
    t2 = next(t for t in tasks if t["scenario_id"] == sid2)
    assert t2["submission_count"] == 2 and t2["own_submitted"] is True and t2["adjudicated"] is False

    # Agreement report: 1 agreed + 1 disagreed -> raw agreement 0.5, 1 disputed scenario
    agreement = client.get("/api/v2/review-panel/agreement").json()["data"]
    assert agreement["multi_rated_scenarios"] == 2
    assert agreement["disputed_count"] == 1
    assert agreement["unadjudicated_disputes"] == 1
    assert agreement["decision_agreement"]["raw_agreement"] == 0.5
    assert agreement["decision_agreement"]["cohens_kappa"] is not None
    assert agreement["specialist_agreement"]["mean_jaccard"] == pytest.approx((1.0 + 1 / 3) / 2, abs=1e-3)

    # Disputed scenario is NOT scored before adjudication; unanimous s1 IS scored
    eval_before = client.post("/api/v2/experiments/evaluate", json={"case_ids": ["LUNG-SYN-001", "LUNG-SYN-002"], "trigger_scope": "all"}).json()["data"]
    assert eval_before["annotated_scenario_count"] == 1

    # Adjudicate s2 -> consensus gold becomes active
    adj_payload = {
        "case_id": s2[0], "case_version": 1, "trigger_event_id": s2[2],
        "adjudicator_id": "chair_md", "required_agents": ["oncology", "pathology"],
        "expected_decision": "NEED_MORE_INFORMATION", "input_sha256": m2["input_sha256"],
        "evidence_ids": [m2_ev], "missing_fields": ["pathology_confirmed"],
        "adjudication_rationale": "病理尚未确诊，应补充资料而非直接暂缓。",
    }
    adj = client.put(f"/api/v2/review-panel/adjudications/{sid2}", json=adj_payload).json()["data"]
    assert adj["resolved_from_annotators"] == ["rater_1", "rater_2"]
    assert "decision" in adj["source_disagreement_types"]

    agreement_after = client.get("/api/v2/review-panel/agreement").json()["data"]
    assert agreement_after["unadjudicated_disputes"] == 0
    assert agreement_after["adjudicated_count"] == 1

    # Export JSONL artifacts and verify CLI loader reads adjudication.jsonl directly
    ann_jsonl = client.get("/api/v2/review-panel/export/annotations.jsonl").text
    adj_jsonl = client.get("/api/v2/review-panel/export/adjudication.jsonl").text
    assert len([line for line in ann_jsonl.splitlines() if line.strip()]) == 4
    assert len([line for line in adj_jsonl.splitlines() if line.strip()]) == 1
    adj_file = tmp_path / "adjudication.jsonl"
    adj_file.write_text(adj_jsonl, encoding="utf-8")
    loaded = load_annotations_file(adj_file)
    assert sid2 in loaded and loaded[sid2]["expected_decision"] == "NEED_MORE_INFORMATION"

    # Evaluate with merged gold: both s1 (unanimous) and s2 (adjudicated) are scored with Macro-F1 & missing-field F1
    eval_after = client.post("/api/v2/experiments/evaluate", json={"case_ids": ["LUNG-SYN-001", "LUNG-SYN-002"], "trigger_scope": "all"}).json()["data"]
    assert eval_after["annotated_scenario_count"] == 2
    b3 = next(m for m in eval_after["methods"] if m["method_id"] == "B3")
    assert b3["macro_f1"] == 1.0
    # LUNG-SYN-002 E003 (molecular_test) misses both molecular_complete and pathology_confirmed;
    # gold listed only pathology_confirmed -> TP=1, FP=1, FN=0 => P=0.5, R=1.0, F1=0.6667
    assert b3["missing_field_precision"] == 0.5
    assert b3["missing_field_recall"] == 1.0
    assert b3["missing_field_f1"] == pytest.approx(2 / 3, abs=1e-4)
    assert b3["confusion_matrix"]["READY_FOR_REVIEW"]["READY_FOR_REVIEW"] == 1
    assert b3["confusion_matrix"]["NEED_MORE_INFORMATION"]["NEED_MORE_INFORMATION"] == 1


def test_independent_temporal_audit_detects_leakages_and_passes_valid_runs(client):
    cases = {c.case_id: c for c in seed_cases()}
    conflict_case = cases["LUNG-SYN-003"]
    req = RunRequest(case_id="LUNG-SYN-003", case_version=1, trigger_event_id="E004", mode="mock", routing_mode="event")
    report = execute(conflict_case, req, "run_audit_ok", lambda *args: None, lambda: False)
    ok_audit = audit_temporal_boundary(conflict_case, report)
    assert ok_audit["passed"] is True
    assert ok_audit["leaked_count"] == 0
    # LUNG-SYN-003 has E002 & E003 on same day, E004 is on its own day; let's also check E002 same-day notice
    req_e2 = RunRequest(case_id="LUNG-SYN-003", case_version=1, trigger_event_id="E002", mode="mock", routing_mode="event")
    rep_e2 = execute(conflict_case, req_e2, "run_audit_e2", lambda *args: None, lambda: False)
    audit_e2 = audit_temporal_boundary(conflict_case, rep_e2)
    assert audit_e2["passed"] is True
    assert set(audit_e2["same_day_events_on_cutoff"]) == {"E002", "E003"}
    assert any(c["code"] == "same_day_ordering_notice" and c["status"] == "warning" for c in audit_e2["checks"])

    # Tamper report to inject future event, unplaced record, out-of-scope citation, and future date in question
    tampered = json.loads(json.dumps(rep_e2))
    tampered["case_snapshot"]["timeline"].append(conflict_case.timeline[-1].model_dump(mode="json"))
    tampered["case_snapshot"]["unplaced_records"] = [{"record_id": "U1", "title": "leaked"}]
    tampered["evidence_registry"].append({"evidence_id": "E004:progression_confirmed", "fact_key": "progression_confirmed", "value": True})
    tampered["final_opinions"][0]["evidence_ids"].append("E004:progression_confirmed")
    tampered["case_snapshot"]["current_question"] = "请结合 2099-12-31 的随访结论判断是否放行。"
    bad_audit = audit_temporal_boundary(conflict_case, tampered)
    assert bad_audit["passed"] is False
    leaked_codes = {item["check_code"] for item in bad_audit["leaked_items"]}
    assert leaked_codes == {
        "snapshot_timeline_boundary",
        "unplaced_records_isolated",
        "evidence_registry_boundary",
        "opinion_citation_boundary",
    }
    assert "2099-12-31" in bad_audit["future_dates_in_question"]

    # HTTP endpoint GET /api/v2/runs/{run_id}/temporal-audit
    created = client.post("/api/v2/runs", json={"case_id": "LUNG-SYN-001", "case_version": 1, "trigger_event_id": "E002", "mode": "mock"}).json()["data"]
    run_id = created["run_id"]
    for _ in range(50):
        snap = client.get(f"/api/v2/runs/{run_id}").json()["data"]
        if snap["report_ready"]:
            break
    audit_resp = client.get(f"/api/v2/runs/{run_id}/temporal-audit")
    assert audit_resp.status_code == 200
    assert audit_resp.json()["data"]["passed"] is True
    assert audit_resp.json()["data"]["excluded_future_event_count"] == 4


def test_first_attempt_llm_telemetry_g01_smoke_and_paired_ablation():
    config = _make_llm_config()
    smoke = run_g01_smoke_suite(
        config,
        transport=_smart_llm_transport(fail_first_citation=True),
        resolver=_public_resolver,
        response_format_mode="json_schema",
    )
    assert "sk-secret-do-not-leak" not in json.dumps(smoke)
    compat = smoke["compatibility"]
    assert compat["connection_passed"] is True
    assert compat["all_scenarios_completed"] is True
    assert compat["all_temporal_audits_passed"] is True
    assert compat["usage_reported_complete"] is True
    assert compat["total_prompt_tokens"] > 0
    # First call injected 1 invalid citation out of 2, then recovered on retry
    totals = compat["validation_totals"]
    assert totals["first_attempt_evidence_failures"] == 1
    assert totals["retry_recovered"] == 1
    assert totals["first_attempt_valid_citations"] < totals["first_attempt_candidate_citations"]

    # Paired LLM ablation across B0, B1, B2, B3, A1, A3, A4
    case = seed_cases()[0]
    matrix = evaluate_llm_ablation_matrix(
        case,
        "E003",
        lambda: RunLLM(config, transport=_smart_llm_transport(), resolver=_public_resolver, response_format_mode="json_object"),
    )
    assert matrix["execution_mode"] == "llm"
    methods = {m["method_id"]: m for m in matrix["methods"]}
    assert set(methods) == {"B0", "B1", "B2", "B3", "A1", "A3", "A4"}
    assert methods["B3"]["final_decision"] == "READY_FOR_REVIEW"
    assert methods["B3"]["agent_calls"] == 2
    assert methods["A3"]["agent_calls"] == 4
    assert matrix["call_saving_pct"] == 50
    assert all(m["temporal_audit_passed"] for m in methods.values())


def test_family_split_error_attribution_and_repro_pack_builder(tmp_path):
    from scripts.build_repro_pack import build_repro_pack

    tcia_file = tmp_path / "tcia.csv"
    tcia_file.write_bytes(tcia_bytes(("R01-001", "R01-002", "R01-003", "R01-004")))

    # Error attribution checks on annotated seed cases
    cases = seed_cases()
    refs = {
        "LUNG-SYN-001:v1:E003": {
            "required_agents": ["oncology", "pathology", "surgery"],
            "expected_decision": "NEED_MORE_INFORMATION",
            "missing_fields": ["imaging_complete"],
        },
    }
    ev = evaluate_library(cases, trigger_scope="all", annotations=refs)
    assert any(row["method_id"] == "B3" and "false_pass" in row["error_types"] and "missed_specialist" in row["error_types"]
               for row in ev["error_analysis"])
    err_rows = list(csv.DictReader(io.StringIO(ev["error_analysis_csv"])))
    assert len(err_rows) == len(ev["error_analysis"])

    # Full §6.4 reproducibility pack
    pack_dir = tmp_path / "repro_pack"
    summary = build_repro_pack(
        sources=[("seed", None, 3), ("tcia_nsclc_csv", tcia_file, 4)],
        output_dir=pack_dir,
        trigger_scope="all",
        dev_ratio=0.3,
        split_seed=2026,
    )
    assert summary["family_count"] == 7
    assert summary["temporal_audit_failed"] == 0
    expected_files = {
        "dataset_manifest.json", "scenario_manifest.jsonl", "experiment_config.json",
        "run_index.jsonl", "scores.csv", "error_analysis.csv",
        "ablation_table.tex", "statistics_summary.json", "reproduce.md",
    }
    assert expected_files <= {p.name for p in pack_dir.iterdir()}

    dm = json.loads((pack_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert dm["split"]["cross_split_family_overlap"] == 0
    assert dm["split"]["dev_family_count"] + dm["split"]["test_family_count"] == 7
    stats = json.loads((pack_dir / "statistics_summary.json").read_text(encoding="utf-8"))
    for key, filename in (
        ("scores_csv_sha256", "scores.csv"),
        ("latex_table_sha256", "ablation_table.tex"),
        ("error_analysis_csv_sha256", "error_analysis.csv"),
    ):
        assert stats["provenance"][key] == hashlib.sha256((pack_dir / filename).read_bytes()).hexdigest()
