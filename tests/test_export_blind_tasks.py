import hashlib
import json
import subprocess
import sys

import pytest

from mdt_demo.research.cohort_freeze import manifest_files, prepare_cohort, publish_cohort
from scripts import export_blind_tasks as exporter


@pytest.fixture
def cohort(tmp_path):
    _, manifest, rows = prepare_cohort([("seed", None, 3)], trigger_scope="all", dev_ratio=0.3, seed=2026)
    directory = tmp_path / "frozen"
    publish_cohort(directory, manifest_files(manifest, rows))
    return directory, rows


def test_cli_hands_off_only_selected_material_and_reproduces_each_fingerprint(cohort, tmp_path, project_root):
    directory, rows = cohort
    output = tmp_path / "assignments" / "dev.jsonl"
    cmd = [sys.executable, str(project_root / "scripts/export_blind_tasks.py"), "--frozen-cohort", str(directory),
           "--output", str(output)]
    assert subprocess.run(cmd, capture_output=True).returncode != 0
    assert not output.exists()
    result = subprocess.run([*cmd, "--split-filter", "dev"], capture_output=True, text=True, check=True)
    contents = output.read_bytes()
    tasks = [json.loads(line) for line in contents.splitlines()]
    dev_rows = [row for row in rows if row["split"] == "dev"]
    assert 0 < len(dev_rows) < len(rows)
    assert f"{len(dev_rows)} 个盲标截点" in result.stdout
    for task, row in zip(tasks, dev_rows, strict=True):
        assert set(task) == {"scenario_id", "events", "input_sha256"}
        assert task["scenario_id"] == row["scenario_id"]
        assert task["events"][-1]["event_id"] == row["trigger_event_id"]
        assert len(task["events"]) == row["visible_event_count"]
        assert all(set(event) == {"event_id", "occurred_at", "event_type", "title", "facts"}
                   and "record_note" not in event["facts"] for event in task["events"])
        material = {key: task[key] for key in ("scenario_id", "events")}
        fingerprint = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")).encode()).hexdigest()
        assert task["input_sha256"] == fingerprint == row["blind_material_sha256"]
    assert exporter.export_blind_tasks(directory, [], "dev", output) == len(tasks)
    with pytest.raises(ValueError, match="已有不同内容"):
        exporter.export_blind_tasks(directory, [], "test", output)
    assert output.read_bytes() == contents


def test_failed_validation_publishes_no_partial_tasks(cohort, tmp_path, monkeypatch):
    directory, rows = cohort
    output = tmp_path / "dev.jsonl"
    wrong = next(row["scenario_id"] for row in reversed(rows) if row["split"] == "dev")
    clean_review = exporter.review_material

    def changed(case, trigger):
        material = clean_review(case, trigger)
        if material["scenario_id"] == wrong:
            material["input_sha256"] = "0" * 64
        return material

    monkeypatch.setattr(exporter, "review_material", changed)
    with pytest.raises(ValueError, match=wrong):
        exporter.export_blind_tasks(directory, [], "dev", output)
    assert not output.exists()
    with pytest.raises(ValueError, match="冻结队列目录之外"):
        exporter.export_blind_tasks(directory, [], "dev", directory / "subdir" / "tasks.jsonl")
    assert not (directory / "subdir").exists()
