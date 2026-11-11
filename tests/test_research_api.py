import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from mdt_demo.research.provider import SettingsService
from mdt_demo.research.store import TERMINAL


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        yield client


def start(client, **updates):
    response = client.post("/api/v2/runs", json={"case_id": "LUNG-SYN-001", "case_version": 1,
                           "trigger_event_id": "E002", **updates})
    assert response.status_code == 202, response.text
    return response.json()["data"]["run_id"]


def finish(client, run_id):
    for _ in range(600):
        snapshot = client.get(f"/api/v2/runs/{run_id}").json()["data"]
        if snapshot["status"] in TERMINAL:
            return snapshot
        time.sleep(.005)
    pytest.fail("Research run did not terminate")


def test_case_append_is_versioned_and_old_report_is_immutable(client):
    run_id = start(client)
    assert finish(client, run_id)["status"] == "completed"
    old_report = client.get(f"/api/v2/runs/{run_id}/report").json()["data"]
    payload = {"expected_version": 1, "event": {"occurred_at": "2026-03-01", "event_type": "pathology",
               "title": "合成病理记录", "facts": {"pathology_confirmed": True}}}
    response = client.post("/api/v2/cases/LUNG-SYN-001/events", json=payload)
    assert response.status_code == 201
    case = response.json()["data"]
    assert case["version"] == 2
    assert case["timeline"][-1]["synthetic_extension"] is True
    assert client.get("/api/v2/cases/LUNG-SYN-001?version=1").json()["data"]["version"] == 1
    assert client.post("/api/v2/cases/LUNG-SYN-001/events", json=payload).status_code == 409
    assert client.get(f"/api/v2/runs/{run_id}/report").json()["data"] == old_report
    new = start(client, case_version=2, trigger_event_id=case["timeline"][-1]["event_id"])
    finish(client, new)
    assert client.get(f"/api/v2/runs/{new}/report").json()["data"]["final_decision"] == "READY_FOR_REVIEW"


def test_event_date_rejects_epoch_number(client):
    response = client.post("/api/v2/cases/LUNG-SYN-001/events", json={"expected_version": 1, "event": {
        "occurred_at": 0, "event_type": "imaging", "title": "invalid", "facts": {"imaging_complete": True}}})
    assert response.status_code == 422


def test_sse_replays_exact_committed_events_and_downloads_match(client):
    run_id = start(client)
    snapshot = finish(client, run_id)
    events = client.get(f"/api/v2/runs/{run_id}/audit").json()["data"]["events"]
    assert [event["seq"] for event in events] == list(range(1, snapshot["last_seq"] + 1))
    stream = client.get(f"/api/v2/runs/{run_id}/events?after_seq=2", headers={"Last-Event-ID": "5"})
    assert stream.headers["content-type"].startswith("text/event-stream")
    decoded = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    assert decoded == events[5:]
    assert decoded[-1]["type"] == "run.completed"
    downloaded = client.get(f"/api/v2/runs/{run_id}/report/download")
    assert downloaded.json()["run_id"] == run_id
    assert "attachment" in downloaded.headers["content-disposition"]
    assert [json.loads(line) for line in client.get(f"/api/v2/runs/{run_id}/audit/download").text.splitlines()] == events
    assert client.get(f"/api/v2/runs/{run_id}/events", headers={"Last-Event-ID": "-2"}).status_code == 422


def test_cancel_never_creates_report_and_survives_restart(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=.1)) as client:
        run_id = start(client)
        assert client.post(f"/api/v2/runs/{run_id}/cancel").status_code == 200
        assert finish(client, run_id)["status"] == "cancelled"
        assert client.get(f"/api/v2/runs/{run_id}/report").status_code == 409
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        assert client.get(f"/api/v2/runs/{run_id}").json()["data"]["status"] == "cancelled"


def test_restart_restores_final_report_and_rerun_gets_new_id(tmp_path):
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        run_id = start(client)
        first = finish(client, run_id)
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        assert client.get(f"/api/v2/runs/{run_id}").json()["data"]["last_seq"] == first["last_seq"]
        rerun = client.post(f"/api/v2/runs/{run_id}/rerun").json()["data"]
        assert rerun["run_id"] != run_id and rerun["source_run_id"] == run_id
        assert finish(client, rerun["run_id"])["report_ready"]


@pytest.mark.parametrize("scenario,status", [("partial_failure", "incomplete"), ("invalid_evidence", "incomplete"), ("persistent_disagreement", "completed")])
def test_abnormal_branches_keep_conservative_report(client, scenario, status):
    run_id = start(client, mock_scenario=scenario)
    snapshot = finish(client, run_id)
    assert snapshot["status"] == status and snapshot["report_ready"]
    report = client.get(f"/api/v2/runs/{run_id}/report").json()["data"]
    assert report["final_decision"] == "DEFER_DECISION"


def test_llm_not_configured_never_falls_back_to_mock(client):
    response = client.post("/api/v2/runs", json={"case_id": "LUNG-SYN-001", "case_version": 1, "trigger_event_id": "E002", "mode": "llm"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
    assert client.get("/api/v2/runs").json()["data"] == []


def test_llm_workflow_uses_frozen_facts_and_never_persists_secret(client):
    contexts = []
    def upstream(request):
        prompt = json.loads(request.content)
        context = json.loads(prompt["messages"][1]["content"])
        contexts.append(context)
        fact = context["evidence_registry"][-1]
        result = {"agent_id": context["agent_id"], "decision": "NEED_MORE_INFORMATION", "summary": "模拟上游的结构化资料检查。",
                  "evidence_ids": [fact["evidence_id"]], "claims": [{"fact_key": fact["fact_key"], "value": fact["value"], "evidence_id": fact["evidence_id"]}],
                  "missing_information": context["missing_information"], "confidence": "medium"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 100, "completion_tokens": 30}})
    client.app.state.research.settings = SettingsService(transport=httpx.MockTransport(upstream), resolver=lambda _: ["93.184.216.34"])
    saved = client.put("/api/v2/settings/llm", json={"base_url": "https://example.test/v1", "model": "test-model", "api_key": "test-never-persist-secret"})
    assert saved.status_code == 200 and "test-never-persist-secret" not in saved.text
    run_id = start(client, mode="llm")
    assert finish(client, run_id)["status"] == "completed"
    report = client.get(f"/api/v2/runs/{run_id}/report").json()["data"]
    assert report["metrics"]["llm_calls"] == 2 and report["metrics"]["prompt_tokens"] == 200
    assert all(len(context["events"]) == 2 for context in contexts)
    assert all(opinion["model_info"]["model"] == "test-model" for opinion in report["final_opinions"])
    audit = client.get(f"/api/v2/runs/{run_id}/audit").text
    assert "test-never-persist-secret" not in json.dumps(report) + audit
    assert client.delete("/api/v2/settings/llm").json()["data"]["has_api_key"] is False


@pytest.mark.parametrize("method", ["put", "delete", "post"])
def test_cross_origin_mutations_cannot_change_model_configuration(client, method):
    response = getattr(client, method)("/api/v2/settings/llm", headers={"Origin": "https://unrelated.example"})
    assert response.status_code == 403
