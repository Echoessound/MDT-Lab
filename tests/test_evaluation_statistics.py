"""Regression fixtures with hand-counted denominators and independent paired labels."""

import csv
import io
import json

import pytest

from mdt_demo.research.evaluation import _build_paired_statistics, evaluate_library
from mdt_demo.research.schemas import ResearchCase
from mdt_demo.research.seeds import seed_cases


READY = "READY_FOR_REVIEW"
NEED = "NEED_MORE_INFORMATION"
DEFER = "DEFER_DECISION"


def record(family, *, b2=NEED, b3=NEED, a2=NEED, b0=NEED, reference=None):
    return {
        "case_family_id": family,
        "b3_calls": 2, "a3_calls": 4,
        "b2_decision": b2, "b3_decision": b3, "a2_decision": a2,
        "a3_decision": b3, "a1_decision": b3, "b0_decision": b0,
        "memory_impacted": False, "expected_decision": reference,
    }


def contrasts(records):
    stats = _build_paired_statistics(records, n_bootstrap=100)
    return {row["contrast_id"]: row for row in stats["contrasts"]}


def test_gate_is_paired_with_b2_and_counts_only_proposed_releases():
    results = contrasts([
        record("a", b2=READY, b3=DEFER, a2=READY),
        record("a", b2=READY, b3=NEED, a2=NEED),
        record("b", b2=READY, b3=None, a2=None),
        record("c", b2=NEED, b3=NEED, a2=NEED),
    ])
    gate = results["B3_vs_B2"]
    assert (gate["metric_numerator"], gate["metric_denominator"]) == (2, 3)
    assert (gate["eligible_scenarios"], gate["total_scenarios"]) == (3, 4)
    assert (gate["eligible_family_count"], gate["point_estimate"]) == (2, 66.67)
    assert (gate["ci_low"], gate["ci_high"]) == (0, 100)
    semantic = results["B3_vs_A2"]
    assert (semantic["metric_numerator"], semantic["metric_denominator"]) == (1, 4)


def test_cluster_resampling_retains_all_paired_events_together():
    # Family a contributes two events with 0 and 100% changes, so its pooled
    # rate is 50%. Family b contributes one unchanged event. Only resampling
    # single events could produce a draw with a 100% change rate.
    records = [record("a", b0=READY), record("a"), record("b")]
    comparison = contrasts(records)["B3_vs_B0"]
    assert comparison["point_estimate"] == 33.33
    assert (comparison["ci_low"], comparison["ci_high"]) == (0, 50)
    assert contrasts(list(reversed(records)))["B3_vs_B0"] == comparison


def test_empty_denominators_and_single_family_do_not_claim_precision():
    for records in ([], [record("a")]):
        gate = contrasts(records)["B3_vs_B2"]
        assert gate["eligible_family_count"] == gate["metric_denominator"] == 0
        assert gate["point_estimate"] is gate["ci_low"] is gate["ci_high"] is None
        assert gate["mcnemar_exact_p"] is None
        assert gate["mcnemar_status"] == "no_annotations"
    only_family = contrasts([record("a"), record("a", b0=READY)])["B3_vs_B0"]
    assert only_family["point_estimate"] == 50
    assert only_family["ci_low"] is only_family["ci_high"] is None


def test_paired_label_test_requires_independent_annotated_families():
    independent = [record(str(i), b0=READY, reference=NEED) for i in range(5)]
    # An unannotated second cutoff in the same family is outside the test.
    comparison = contrasts([*independent, record("0")])["B3_vs_B0"]
    assert comparison["mcnemar_status"] == "ok"
    assert comparison["annotated_pairs"] == comparison["b3_only_correct"] == 5
    assert comparison["comparator_only_correct"] == 0
    assert comparison["mcnemar_exact_p"] == pytest.approx(2 / 32)

    duplicate = contrasts([*independent, record("0", b3=READY, reference=NEED)])["B3_vs_B0"]
    assert duplicate["annotated_pairs"] == 6
    assert duplicate["comparator_only_correct"] == 1
    assert duplicate["mcnemar_status"] == "repeated_family"
    assert duplicate["mcnemar_exact_p"] is None
    concordant = contrasts([record("a", reference=NEED)])["B3_vs_B0"]
    assert concordant["b3_only_correct"] == concordant["comparator_only_correct"] == 0
    assert concordant["mcnemar_exact_p"] == 1.0


def test_exported_scores_reproduce_annotated_safety_and_routing_metrics():
    references = {
        "LUNG-SYN-001:v1:E006": {"required_agents": ["oncology", "radiology"], "expected_decision": NEED},
        "LUNG-SYN-002:v1:E003": {"required_agents": ["surgery"], "expected_decision": READY},
    }
    result = evaluate_library(seed_cases(), trigger_scope="latest", annotations=references)
    rows = list(csv.DictReader(io.StringIO(result["scores_csv"])))
    for summary in result["methods"]:
        selected = [r for r in rows if r["method_id"] == summary["method_id"]]
        reviewed = [r for r in selected if r["expected_decision"]]
        assert len(reviewed) == summary["annotated_count"] == 2
        rec = 0.0
        for row in reviewed:
            required = set(json.loads(row["required_agents"]))
            hits = len(required.intersection(json.loads(row["selected_agents"])))
            assert hits == int(row["required_agent_hits"])
            assert len(required) == int(row["required_agent_count"])
            rec += hits / len(required)
        assert summary["specialist_recall"] == round(rec / summary["specialist_recall_scenarios"], 4)
        false_pass = sum(r["final_decision"] == READY and r["expected_decision"] == NEED for r in reviewed)
        over_deferral = sum(r["final_decision"] in {NEED, DEFER} and r["expected_decision"] == READY for r in reviewed)
        assert (summary["false_pass_count"], summary["false_pass_denominator"]) == (false_pass, 1)
        assert (summary["over_deferral_count"], summary["over_deferral_denominator"]) == (over_deferral, 1)
        assert all(r["required_agent_count"] == "" for r in selected if not r["expected_decision"])


def test_export_distinguishes_scenario_cutoff_from_each_methods_actual_input():
    payload = seed_cases()[0].model_dump(mode="json")
    first, second = payload["timeline"][:2]
    payload["timeline"] = [
        {**first, "event_type": "imaging", "facts": {"imaging_complete": True}},
        {**second, "event_type": "pathology", "facts": {"histology": "Adenocarcinoma"}},
    ]
    case = ResearchCase.model_validate(payload)
    result = evaluate_library([case], trigger_scope="latest")
    rows = {r["method_id"]: r for r in csv.DictReader(io.StringIO(result["scores_csv"]))}
    for row in rows.values():
        assert (row["case_version"], row["trigger_event_id"], row["visible_events"]) == ("1", "E002", "2")
    for mid in ("B0", "B1", "B2", "B3", "A3", "A4"):
        row = rows[mid]
        assert (row["input_case_version"], row["input_trigger_event_id"], row["method_visible_events"]) == (
            "1", "E002", "2")
    assert rows["B2"]["trajectory_id"] == rows["B3"]["trajectory_id"] == "B3"
    assert rows["A1"]["method_visible_events"] == "1"
    assert rows["A2"]["input_case_version"] == "2"
    assert rows["A2"]["input_trigger_event_id"] != rows["A2"]["trigger_event_id"]
    assert rows["A2"]["method_visible_events"] == "3"
    assert rows["A2"]["trajectory_id"] == "A2"
