import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from mdt_demo.api_schemas import APIError
from mdt_demo.research.blind_review import review_material
from mdt_demo.research.evaluation import evaluate_library
from mdt_demo.research.schemas import ResearchCase
from mdt_demo.research.seeds import seed_cases


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as session:
        yield session


def test_task_list_and_material_do_not_disclose_later_or_author_information(client):
    tasks = client.get("/api/v2/annotations/tasks").json()["data"]
    assert len(tasks) == 13
    assert all(set(row) == {"scenario_id", "case_id", "case_version", "trigger_event_id", "annotated"}
               for row in tasks)
    params = {"case_id": "LUNG-SYN-003", "version": 1, "trigger_event_id": "E002"}
    material = client.get("/api/v2/annotations/material", params=params).json()["data"]
    assert set(material) == {"scenario_id", "events", "input_sha256"}
    assert material["scenario_id"] == "LUNG-SYN-003:v1:E002"
    assert [event["event_id"] for event in material["events"]] == ["E001", "E002"]
    assert all(set(event) == {"event_id", "occurred_at", "event_type", "title", "facts"}
               for event in material["events"])
    assert "冲突" not in json.dumps(material, ensure_ascii=False)
    assert material["events"][-1]["facts"]["progression_confirmed"] is False
    assert client.get("/api/v2/annotations/material", params={**params, "trigger_event_id": "UNKNOWN"}).status_code == 404
    assert client.get("/api/v2/annotations/material", params={**params, "version": 9}).status_code == 404


def test_reference_version_evidence_and_reviewer_binding(client):
    base = "/api/v2/annotations"
    scenario = "LUNG-SYN-003:v1:E002"
    params = {"case_id": "LUNG-SYN-003", "version": 1, "trigger_event_id": "E002"}
    material = client.get(f"{base}/material", params=params).json()["data"]
    payload = {
        "case_id": params["case_id"], "case_version": 1, "trigger_event_id": params["trigger_event_id"],
        "annotator_id": "reader_a", "required_agents": ["radiology"], "expected_decision": "READY_FOR_REVIEW",
        "evidence_ids": ["E002:imaging_complete"], "missing_fields": ["histology"],
    }
    path = f"{base}/{scenario}"
    for ref in ("E003:imaging_complete", "E002:record_note", "E002:nonexistent"):
        result = client.put(path, json={**payload, "evidence_ids": [ref]})
        assert (result.status_code, result.json()["error"]["code"]) == (422, "ANNOTATION_EVIDENCE_OUT_OF_SCOPE")
    mismatch = client.put(path, json={**payload, "input_sha256": "0" * 64})
    assert (mismatch.status_code, mismatch.json()["error"]["code"]) == (409, "ANNOTATION_INPUT_MISMATCH")
    record = client.put(path, json=payload).json()["data"]
    assert record["input_sha256"] == material["input_sha256"]
    assert record["evidence_ids"] == payload["evidence_ids"]
    assert client.put(path, json={**payload, "input_sha256": material["input_sha256"]}).status_code == 200
    assert client.put(path, json={**payload, "annotator_id": "reader_b"}).json()["error"]["code"] == "ANNOTATION_REVIEWER_CONFLICT"
    query = {"scenario_id": scenario, "annotator_id": "reader_b"}
    assert client.get(f"{base}/own", params=query).json()["data"] is None
    own = client.get(f"{base}/own", params={**query, "annotator_id": "reader_a"}).json()["data"]
    assert own["missing_fields"] == ["histology"]
    assert client.delete(path, params={"annotator_id": "reader_b"}).status_code == 409
    tasks = client.get(f"{base}/tasks").json()["data"]
    assert [row["scenario_id"] for row in tasks if row["annotated"]] == [scenario]
    assert client.delete(path, params={"annotator_id": "reader_a"}).status_code == 200


def test_reference_scoring_checks_the_reviewed_content_and_accepts_legacy_labels():
    case = seed_cases()[0]
    trigger_id = case.timeline[0].event_id
    material = review_material(case, trigger_id)
    scenario = material["scenario_id"]
    payload = case.model_dump(mode="json")
    payload["title"] = "Retrospective case label"
    payload["timeline"][-1]["facts"]["outcome"] = "future observation"
    payload["timeline"][0]["facts"]["expected_decision"] = "DEFER_DECISION"
    assert review_material(ResearchCase.model_validate(payload), trigger_id) == material
    payload["timeline"][0]["facts"]["custom_lab_value"] = 1.75
    changed = ResearchCase.model_validate(payload)
    changed_material = review_material(changed, trigger_id)
    assert changed_material["events"][0]["facts"]["custom_lab_value"] == 1.75
    assert changed_material["input_sha256"] != material["input_sha256"]
    ann = {"expected_decision": "READY_FOR_REVIEW", "required_agents": ["oncology"]}
    with pytest.raises(APIError) as error:
        evaluate_library([changed], annotations={scenario: {**ann, "input_sha256": material["input_sha256"]}})
    assert error.value.code == "ANNOTATION_INPUT_MISMATCH"
    assert evaluate_library([case], annotations={scenario: ann})["annotated_scenario_count"] == 1


def test_changed_reference_fails_through_web_and_cli(tmp_path, project_root):
    scenario = "LUNG-SYN-001:v1:E006"
    query = {"scenario_id": scenario, "annotator_id": "reader_a"}
    record = {
        **query, "case_id": "LUNG-SYN-001", "case_version": 1, "trigger_event_id": "E006",
        "required_agents": ["oncology"], "expected_decision": "READY_FOR_REVIEW",
        "input_sha256": "0" * 64,
    }
    annotations = tmp_path / "annotations.json"
    annotations.write_text(json.dumps({scenario: record}), encoding="utf-8")
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        outdated = client.post("/api/v2/experiments/evaluate", json={"trigger_scope": "latest"})
        assert (outdated.status_code, outdated.json()["error"]["code"]) == (409, "ANNOTATION_INPUT_MISMATCH")
    destination = tmp_path / "paper"
    cli = subprocess.run([
        sys.executable, str(project_root / "scripts/run_mock_experiments.py"),
        "--triggers", "latest", "--max-cases", "1", "--annotations", str(annotations),
        "--output-dir", str(destination),
    ], capture_output=True, text=True, check=False)
    assert cli.returncode == 2
    assert "ANNOTATION_INPUT_MISMATCH" in cli.stderr
    assert not (destination / "scores.csv").exists()
