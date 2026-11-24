"""Reproduction checks for the offline experiment entry point and checkpoint."""
from contextlib import closing
import csv
import hashlib
import json
import runpy
import sqlite3
import subprocess
import sys

import pytest

from mdt_demo.research import experiments as batch
from test_dataset_import import tcia_bytes


def test_batch_cli_freezes_tcia_inputs_and_preserves_a_bound_batch(tmp_path, project_root):
    source = tmp_path / "cases.csv"
    source.write_bytes(tcia_bytes(("R01-001",)))
    destination = tmp_path / "batch"
    command = [sys.executable, str(project_root / "scripts/run_mock_experiments.py"),
               "--source", "tcia_nsclc_csv", "--input", str(source), "--output-dir", str(destination)]
    subprocess.run(command, check=True)
    result_file = destination / "results.json"
    original = result_file.read_bytes()
    report = json.loads(original)
    plan = report["manifest"]
    assert report["summary"] == {"families": 1, "scenarios": 2, "completed": 2, "failed": 0, "method_rows": 16}
    assert len(plan["dataset"]["artifact_sha256"]) == 64
    assert plan["families"][0]["unplaced_record_count"] > 0
    assert [row["visible_event_count"] for row in plan["scenarios"]] == [1, 2]
    assert len({row["frozen_input_sha256"] for row in plan["scenarios"]}) == 2
    for attempt in report["attempts"]:
        methods = {row["method_id"]: row for row in attempt["result"]["methods"]}
        assert methods["A2"]["final_decision"] == methods["B3"]["final_decision"] == "NEED_MORE_INFORMATION"
    subprocess.run(command, check=True)
    assert result_file.read_bytes() == original
    assert subprocess.run([*command, "--triggers", "latest"]).returncode != 0
    assert result_file.read_bytes() == original


def test_resume_retries_failed_scenario_and_keeps_first_attempt(tmp_path, monkeypatch):
    cases, dataset = batch.load_cases("seed", None, 1)
    plan = batch.plan_batch(cases, dataset, "latest")
    scenario, = plan["scenarios"]
    original = batch.workflow_designer.evaluate_ablation_matrix

    def fail_once(*args):
        raise RuntimeError("source values do not belong in an error record")

    with closing(sqlite3.connect(":memory:")) as db:
        batch.bind_plan(db, plan)
        monkeypatch.setattr(batch.workflow_designer, "evaluate_ablation_matrix", fail_once)
        batch.run_scenario(db, cases[0], scenario)
        assert batch.export_results(db, plan, tmp_path)["failed"] == 1
        monkeypatch.setattr(batch.workflow_designer, "evaluate_ablation_matrix", original)
        batch.run_scenario(db, cases[0], scenario)
        batch.run_scenario(db, cases[0], scenario)
        assert batch.export_results(db, plan, tmp_path)["completed"] == 1
    rows = json.loads((tmp_path / "results.json").read_text())["attempts"]
    assert [(row["attempt"], row["status"]) for row in rows] == [(1, "failed"), (2, "completed")]
    assert rows[0]["result"] == {"error_type": "RuntimeError"}


def test_cli_scores_only_recorded_successes_after_resume(tmp_path, project_root, monkeypatch):
    cli = project_root / "scripts/run_mock_experiments.py"
    run = runpy.run_path(str(cli))["main"]
    destination = tmp_path / "batch"
    ann_file = tmp_path / "annotations.json"
    cases = batch.seeds.seed_cases()[:2]
    latest_sid = f"{cases[0].case_id}:v1:{cases[0].timeline[-1].event_id}"
    early_sid = f"{cases[0].case_id}:v1:{cases[0].timeline[0].event_id}"
    fields = {"expected_decision": "DEFER_DECISION", "required_agents": ["oncology"]}
    ann_file.write_text(json.dumps({latest_sid: fields, early_sid: fields}))
    monkeypatch.setattr(sys, "argv", [str(cli), "--max-cases", "2", "--triggers", "latest",
                                     "--output-dir", str(destination), "--annotations", str(ann_file)])
    actual = batch.workflow_designer.evaluate_ablation_matrix
    calls = []

    def record_or_fail(case, trigger):
        calls.append(case.case_id)
        if case.case_id == cases[1].case_id and len(calls) == 2:
            raise RuntimeError("transient simulation error")
        return actual(case, trigger)

    def reject_reexecution(*args):
        raise AssertionError("paper export must read saved matrices")

    monkeypatch.setattr(batch.workflow_designer, "evaluate_ablation_matrix", record_or_fail)
    monkeypatch.setattr(batch.evaluation, "evaluate_ablation_matrix", reject_reexecution)
    assert run() == 1
    result_path = destination / "results.json"
    assert json.loads(result_path.read_text())["summary"]["failed"] == 1
    for name in ("scores.csv", "ablation_table.tex", "statistics_summary.json"):
        assert not (destination / name).exists()

    assert run() == 0
    assert calls == [cases[0].case_id, cases[1].case_id, cases[1].case_id]
    results = json.loads(result_path.read_text())
    stats_path = destination / "statistics_summary.json"
    stats = json.loads(stats_path.read_text())
    assert stats["family_count"] == stats["scenario_count"] == 2
    assert stats["annotated_scenario_count"] == 1
    provenance = stats["provenance"]
    assert provenance["manifest_sha256"] == results["manifest_sha256"]
    assert provenance["annotations_outside_scope"] == 1
    assert provenance["annotations_with_input_sha256"] == 0
    for key, name in (("results_sha256", "results.json"), ("scores_csv_sha256", "scores.csv"),
                      ("latex_table_sha256", "ablation_table.tex")):
        assert provenance[key] == hashlib.sha256((destination / name).read_bytes()).hexdigest()
    checkpoint_rows = {
        (attempt["scenario_id"], method["method_id"]): method["agent_calls"]
        for attempt in results["attempts"] if attempt["status"] == "completed"
        for method in attempt["result"]["methods"]
    }
    with (destination / "scores.csv").open(newline="") as stream:
        assert {(row["scenario_id"], row["method_id"]): int(row["agent_calls"])
                for row in csv.DictReader(stream)} == checkpoint_rows

    original_results = result_path.read_bytes()
    frozen = batch.engine.freeze_context(cases[0], cases[0].timeline[-1].event_id)
    material = batch.evaluation.material_from_frozen(frozen)
    event = next(event for event in material["events"] if event["facts"])
    bound_annotation = {**fields, "expected_decision": "READY_FOR_REVIEW",
                        "input_sha256": material["input_sha256"],
                        "evidence_ids": [f"{event['event_id']}:{next(iter(event['facts']))}"]}
    ann_file.write_text(json.dumps({latest_sid: bound_annotation}))
    assert run() == 0
    assert len(calls) == 3
    assert result_path.read_bytes() == original_results
    revised = json.loads(stats_path.read_text())["provenance"]
    assert revised["annotations_outside_scope"] == 0
    assert revised["annotations_with_input_sha256"] == 1
    assert revised["scored_annotations_sha256"] != provenance["scored_annotations_sha256"]
    scored_artifacts = {name: (destination / name).read_bytes()
                        for name in ("scores.csv", "ablation_table.tex", "statistics_summary.json")}
    for invalid in ({"input_sha256": "0" * 64}, {"evidence_ids": ["OTHER:future"]}):
        ann_file.write_text(json.dumps({latest_sid: {**bound_annotation, **invalid}}))
        with pytest.raises(SystemExit) as error:
            run()
        assert error.value.code == 2
        assert len(calls) == 3
        for name, original_bytes in scored_artifacts.items():
            assert (destination / name).read_bytes() == original_bytes


def test_annotation_exports_reject_duplicate_incomplete_or_mismatched_records(tmp_path):
    path = tmp_path / "annotations.json"
    sid = "LUNG-SYN-001:v1:E002"
    ann = {"scenario_id": sid, "required_agents": ["oncology"], "expected_decision": "DEFER_DECISION"}
    for value in ([ann, ann], [ann, False], {"items": [{}]}, {sid: {**ann, "case_version": 2}},
                  {sid: {**ann, "scenario_id": "LUNG-SYN-002:v1:E002"}},
                  {sid: {**ann, "expected_decision": "UNKNOWN"}}):
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            batch.load_annotations_file(path)
    record = json.dumps(ann)
    path.write_text(f'{{"{sid}":{record},"{sid}":{record}}}')
    with pytest.raises(ValueError, match="重复键"):
        batch.load_annotations_file(path)
    for value in ([ann], {"items": [ann]}, {sid: ann}):
        path.write_text(json.dumps(value))
        assert batch.load_annotations_file(path)[sid]["expected_decision"] == ann["expected_decision"]
