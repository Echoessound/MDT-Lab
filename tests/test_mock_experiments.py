"""Reproduction checks for the offline experiment entry point and checkpoint."""
from contextlib import closing
import json
import sqlite3
import subprocess
import sys

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
