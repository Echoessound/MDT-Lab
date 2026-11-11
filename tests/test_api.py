import json
import time

import pytest
from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from mdt_demo.runtime import TERMINAL


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as browser:
        yield browser


def start(client, scenario="standard"):
    response = client.post("/api/v1/runs", json={
        "case_id": "SYN-001", "mode": "mock", "options": {"scenario": scenario},
    })
    assert response.status_code == 202, response.text
    return response.json()["data"]["run_id"]


def finished(client, run_id):
    for _ in range(500):
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        snapshot = response.json()["data"]
        if snapshot["status"] in TERMINAL:
            return snapshot
        time.sleep(0.005)
    pytest.fail("Run did not terminate within 2.5 seconds")


def test_case_contract_and_not_found(client):
    response = client.get("/api/v1/cases")
    assert response.status_code == 200
    assert response.json()["data"][0]["is_synthetic"] is True
    assert response.headers["x-request-id"].startswith("req_")
    assert client.get("/api/v1/cases/SYN-001").json()["data"]["timeline"][1]["event_id"] == "E002"
    missing = client.get("/api/v1/cases/missing")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "CASE_NOT_FOUND"


@pytest.mark.parametrize("scenario,decision,status,rounds", [
    ("standard", "NEED_MORE_INFORMATION", "completed", 1),
    ("aligned", "NEED_MORE_INFORMATION", "completed", 0),
    ("partial_failure", "DEFER_DECISION", "incomplete", 0),
    ("persistent_disagreement", "DEFER_DECISION", "completed", 1),
])
def test_scenarios_produce_real_reports_and_monotonic_events(client, tmp_path, scenario, decision, status, rounds):
    run_id = start(client, scenario)
    snapshot = finished(client, run_id)
    report_response = client.get(f"/api/v1/runs/{run_id}/report")
    assert report_response.status_code == 200
    report = report_response.json()["data"]
    assert snapshot["status"] == status == report["status"]
    assert snapshot["report_ready"] is True
    assert report["final_decision"] == decision and report["discussion_rounds"] == rounds
    events = client.get(f"/api/v1/runs/{run_id}/audit").json()["data"]["events"]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert snapshot["last_seq"] == len(events)
    assert all(event["payload"]["run_id"] == run_id for event in events)
    assert events[-1]["type"] == "run.completed"
    assert json.loads((tmp_path / run_id / "report.json").read_text())["final_decision"] == decision
    if scenario == "partial_failure":
        assert snapshot["agents"]["surgery"]["status"] == "failed"
        assert len(report["final_opinions"]) == 2
    if scenario == "persistent_disagreement":
        assert report["unresolved_disagreements"]
    if scenario == "aligned":
        assert not any(event["payload"]["stage"] == "TARGETED_DISCUSSION" for event in events)


def test_websocket_replay_and_incremental_audit(client):
    run_id = start(client)
    snapshot = finished(client, run_id)
    received = []
    with client.websocket_connect(f"/api/v1/runs/{run_id}/events?after_seq=5") as socket:
        for _ in range(snapshot["last_seq"] - 5):
            received.append(socket.receive_json())
    assert [event["seq"] for event in received] == list(range(6, snapshot["last_seq"] + 1))
    assert received[-1]["type"] == "run.completed"
    page = client.get(f"/api/v1/runs/{run_id}/audit?after_seq=5&limit=3").json()["data"]
    assert [event["seq"] for event in page["events"]] == [6, 7, 8]
    assert page["next_seq"] == 8


def test_cancel_is_durable_and_never_produces_success_report(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0.2)) as client:
        run_id = start(client)
        assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200
        snapshot = finished(client, run_id)
        assert snapshot["status"] == "cancelled" and not snapshot["report_ready"]
        assert not (tmp_path / run_id / "report.json").exists()
        assert client.get(f"/api/v1/runs/{run_id}/report").status_code == 409
        events = client.get(f"/api/v1/runs/{run_id}/audit").json()["data"]["events"]
        assert events[-1]["type"] == "run.cancelled"
        assert any(event["type"] == "run.cancel_requested" for event in events)
    with TestClient(create_app(tmp_path, event_delay=0)) as restarted:
        assert restarted.get(f"/api/v1/runs/{run_id}").json()["data"]["status"] == "cancelled"


def test_rerun_gets_new_id_and_preserves_source(client):
    run_id = start(client)
    finished(client, run_id)
    rerun = client.post(f"/api/v1/runs/{run_id}/rerun").json()["data"]
    assert rerun["run_id"] != run_id and rerun["source_run_id"] == run_id
    finished(client, rerun["run_id"])
    assert len(client.get("/api/v1/runs").json()["data"]) == 2


def test_report_and_audit_downloads_are_actual_files(client):
    run_id = start(client)
    finished(client, run_id)
    report = client.get(f"/api/v1/runs/{run_id}/report/download")
    assert report.status_code == 200 and "attachment" in report.headers["content-disposition"]
    assert report.json()["run_id"] == run_id
    audit = client.get(f"/api/v1/runs/{run_id}/audit/download")
    assert audit.status_code == 200
    assert json.loads(audit.text.splitlines()[-1])["event_type"] == "run_finished"


def test_completed_run_is_restored_after_restart(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as first:
        run_id = start(first)
        original = finished(first, run_id)
    with TestClient(create_app(tmp_path, event_delay=0)) as second:
        restored = second.get(f"/api/v1/runs/{run_id}").json()["data"]
        assert restored["last_seq"] == original["last_seq"]
        assert restored["status"] == original["status"]
        assert restored["agents"]["surgery"]["opinion"]["decision"] == "NEED_MORE_INFORMATION"
        assert second.get(f"/api/v1/runs/{run_id}/report").status_code == 200


def test_unavailable_llm_and_invalid_parameters_are_explicit(client):
    assert client.get("/api/v1/llm/status").json()["data"]["enabled"] is False
    response = client.post("/api/v1/runs", json={"case_id": "SYN-001", "mode": "llm"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "LLM_NOT_AVAILABLE"
    invalid = client.post("/api/v1/runs", json={"case_id": "SYN-001", "options": {"max_discussion_rounds": 2}})
    assert invalid.status_code == 422 and invalid.json()["error"]["details"]
    assert client.get("/api/v1/runs/missing").status_code == 404
    assert client.get("/api/v1/unknown").status_code == 404


def test_stop_after_completion_is_conflict(client):
    run_id = start(client)
    finished(client, run_id)
    assert client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 409


def test_cross_origin_post_is_rejected(client):
    response = client.post("/api/v1/runs", headers={"Origin": "https://unrelated.example"}, json={"case_id": "SYN-001"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
