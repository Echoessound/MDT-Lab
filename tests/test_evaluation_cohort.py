from fastapi.testclient import TestClient

from mdt_demo.api import create_app


def test_paired_evaluation_replays_the_selected_case_revision(tmp_path):
    case_id = "LUNG-SYN-001"
    selection = {"case_ids": [case_id], "trigger_scope": "latest"}
    frozen = {**selection, "case_versions": {case_id: 1}}
    url = "/api/v2/experiments/evaluate"
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        before = client.post(url, json=frozen).json()["data"]
        updated = client.post(f"/api/v2/cases/{case_id}/events", json={
            "expected_version": 1, "event": {"occurred_at": "2026-03-10", "event_type": "observation",
                                           "title": "新增观察记录", "facts": {"observation_reviewed": True}},
        })
        assert updated.status_code == 201
        replay = client.post(url, json=frozen).json()["data"]
        assert replay["scenarios"] == before["scenarios"]
        assert replay["scores_csv"] == before["scores_csv"]
        assert replay["scenarios"][0]["case_version"] == 1
        latest = client.post(url, json=selection).json()["data"]
        assert latest["scenarios"][0]["case_version"] == 2
        assert latest["scenarios"][0]["trigger_event_id"] == updated.json()["data"]["timeline"][-1]["event_id"]
        all_latest = client.post(url, json={"trigger_scope": "latest"}).json()["data"]
        assert all_latest["family_count"] == 3


def test_incomplete_unknown_or_invalid_selections_never_score_a_partial_cohort(tmp_path):
    case_id = "LUNG-SYN-001"
    url = "/api/v2/experiments/evaluate"
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        for payload, status, code in [
            ({"case_ids": []}, 422, "INVALID_CASE_SELECTION"),
            ({"case_ids": [case_id, case_id]}, 422, "INVALID_CASE_SELECTION"),
            ({"case_ids": [case_id, "MISSING"]}, 404, "CASE_NOT_FOUND"),
            ({"case_ids": [case_id], "case_versions": {case_id: 2}}, 404, "CASE_NOT_FOUND"),
            ({"case_ids": [case_id], "case_versions": {}}, 422, "CASE_SELECTION_MISMATCH"),
            ({"case_ids": [case_id], "case_versions": {case_id: 1, "MISSING": 1}}, 422, "CASE_SELECTION_MISMATCH"),
            ({"case_versions": {case_id: 1}}, 422, "CASE_SELECTION_MISMATCH"),
        ]:
            response = client.post(url, json=payload)
            assert (response.status_code, response.json()["error"]["code"]) == (status, code)
        for version in (0, True, "1"):
            response = client.post(url, json={"case_ids": [case_id], "case_versions": {case_id: version}})
            assert response.status_code == 422
