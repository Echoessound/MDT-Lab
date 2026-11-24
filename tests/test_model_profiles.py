"""Named model profiles through the local FastAPI entry points and an in-memory upstream."""

import json
from threading import Event

import httpx
from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from test_research_api import finish, start
from test_research_provider import config, output, response


DEFAULT = "/api/v2/settings/llm"
AGENTS = "/api/v2/settings/agents"
PROFILES = f"{DEFAULT}/profiles"


def create_profile(client, name, **fields):
    result = client.post(PROFILES, json={"name": name, **config(**fields)})
    assert result.status_code == 201, result.text
    return result.json()["data"]["profile_id"]


def activate(client, profile_id, scope):
    result = client.post(f"{PROFILES}/{profile_id}/activate", json={"scope": scope})
    assert result.status_code == 200, result.text
    return result.json()["data"]


def read(client, route):
    result = client.get(route)
    assert result.status_code == 200, result.text
    return result.json()["data"]


def stub_upstream(client, handler):
    settings = client.app.state.research.settings
    settings._transport = httpx.MockTransport(handler)
    settings._resolver = lambda _host: ["93.184.216.34"]


def test_profile_bindings_coexist_with_direct_settings_and_survive_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.put(DEFAULT, json=config(model="legacy-default")).status_code == 200
        assert client.put(f"{AGENTS}/surgery", json=config(model="legacy-surgery")).status_code == 200
        shared = create_profile(client, "共享配置", model="shared-model")
        task = create_profile(client, "影像配置", model="imaging-model")
        assert read(client, DEFAULT)["model"] == "legacy-default"
        assert activate(client, shared, "default")["profile_id"] == shared
        assert activate(client, task, "radiology")["profile_id"] == task

    with TestClient(create_app(tmp_path)) as client:
        listed = {item["profile_id"]: item for item in read(client, PROFILES)}
        assert {pid: item["name"] for pid, item in listed.items()} == {shared: "共享配置", task: "影像配置"}
        assert read(client, DEFAULT)["profile_id"] == shared
        inherited = read(client, f"{AGENTS}/pathology")
        assert (inherited["configuration_source"], inherited["profile_id"], inherited["model"]) == (
            "default", shared, "shared-model")
        explicit = read(client, f"{AGENTS}/radiology")
        assert (explicit["configuration_source"], explicit["profile_id"], explicit["model"]) == (
            "agent", task, "imaging-model")
        assert read(client, f"{AGENTS}/surgery")["model"] == "legacy-surgery"
        for profile_id in (task, shared):
            blocked = client.delete(f"{PROFILES}/{profile_id}")
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "LLM_PROFILE_IN_USE"

        # A role inheriting the default has never had its own credential.
        assert client.put(f"{AGENTS}/pathology", json=config(api_key="")).status_code == 422
        assert read(client, f"{AGENTS}/pathology")["profile_id"] == shared
        assert client.put(f"{AGENTS}/radiology", json=config(api_key="", model="direct-role")).status_code == 422
        assert read(client, f"{AGENTS}/radiology")["profile_id"] == task
        direct = client.put(f"{AGENTS}/radiology", json=config(api_key="fixture-role-direct", model="direct-role"))
        assert direct.status_code == 200 and direct.json()["data"].get("profile_id") is None
        assert next(item for item in read(client, PROFILES) if item["profile_id"] == task)["model"] == "imaging-model"
        assert client.delete(f"{PROFILES}/{task}").status_code == 200
        fallback = client.delete(f"{AGENTS}/radiology").json()["data"]
        assert fallback["profile_id"] == shared and fallback["configuration_source"] == "default"
        assert client.put(DEFAULT, json=config(api_key="", model="direct-shared")).status_code == 422
        direct = client.put(DEFAULT, json=config(api_key="fixture-default-direct", model="direct-shared"))
        assert direct.status_code == 200 and direct.json()["data"].get("profile_id") is None
        assert client.delete(f"{PROFILES}/{shared}").status_code == 200
        assert read(client, f"{AGENTS}/radiology")["model"] == "direct-shared"
    with TestClient(create_app(tmp_path)) as client:
        assert read(client, PROFILES) == []
        assert read(client, f"{AGENTS}/oncology")["model"] == "direct-shared"
        assert read(client, f"{AGENTS}/surgery")["model"] == "legacy-surgery"


def test_copy_from_effective_scope_retains_an_independent_credential(tmp_path):
    calls = []

    def handler(request):
        calls.append((request.headers["authorization"], json.loads(request.content)["model"]))
        return response({"ok": True})

    copy_url = f"{PROFILES}/from-scope"
    with TestClient(create_app(tmp_path)) as client:
        stub_upstream(client, handler)
        assert client.post(copy_url, json={"scope": "default", "name": "未配置"}).status_code == 409
        assert client.put(DEFAULT, json=config(model="original", api_key="fixture-copy-source")).status_code == 200
        copy = client.post(copy_url, json={"scope": "oncology", "name": "继承时保存"})
        assert copy.status_code == 201, copy.text
        profile_id = copy.json()["data"]["profile_id"]
        assert "fixture-copy-source" not in copy.text
        assert read(client, DEFAULT).get("profile_id") is None
        assert client.post(copy_url, json={"scope": "default", "name": "继承时保存"}).status_code == 409
        assert client.put(DEFAULT, json=config(model="replacement", api_key="fixture-copy-new")).status_code == 200
        assert client.post(f"{PROFILES}/{profile_id}/test").json()["data"]["ok"]
        assert client.post(f"{DEFAULT}/test").json()["data"]["ok"]
        assert activate(client, profile_id, "default")["model"] == "original"
        assert client.post(f"{DEFAULT}/test").json()["data"]["ok"]
        assert calls == [("Bearer fixture-copy-source", "original"), ("Bearer fixture-copy-new", "replacement"),
                         ("Bearer fixture-copy-source", "original")]


def test_inactive_profile_probe_and_key_rotation_are_isolated(tmp_path):
    calls = []
    original_key, rotated_key = "fixture-profile-key-A", "fixture-profile-key-B"

    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.host, request.headers["authorization"], body["model"]))
        assert "case_id" not in str(body) and "evidence_registry" not in str(body)
        return response({"ok": True})

    with TestClient(create_app(tmp_path)) as client:
        stub_upstream(client, handler)
        missing = client.post(PROFILES, json={"name": "A", **config(api_key="")})
        assert missing.status_code == 422 and missing.json()["error"]["code"] == "LLM_KEY_REQUIRED"
        profile_id = create_profile(client, "Candidate", api_key=original_key)
        endpoint = f"{PROFILES}/{profile_id}"
        duplicate = client.post(PROFILES, json={"name": "candidate", **config(api_key=rotated_key)})
        assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "LLM_PROFILE_NAME_CONFLICT"
        assert not read(client, DEFAULT)["configured"]
        updated = client.put(endpoint, json={"name": "候选", **config(model="model-A2", api_key="")})
        assert updated.status_code == 200 and updated.json()["data"]["has_api_key"]
        new_url = "https://second.example.test/v1"
        changed = {"name": "替换", **config(base_url=new_url, model="model-B", api_key="")}
        denied = client.put(endpoint, json=changed)
        assert denied.status_code == 422 and denied.json()["error"]["code"] == "LLM_KEY_REQUIRED"
        assert client.put(endpoint, json={**changed, "api_key": rotated_key},
                          headers={"Origin": "https://untrusted.example"}).status_code == 403
        first_probe = client.post(f"{endpoint}/test")
        assert first_probe.status_code == 200 and first_probe.json()["data"]["ok"]
        assert client.put(endpoint, json={**changed, "api_key": rotated_key}).status_code == 200
        assert client.post(f"{endpoint}/test").json()["data"]["ok"]
        assert not read(client, DEFAULT)["configured"]
        assert calls == [("api.example.test", f"Bearer {original_key}", "model-A2"),
                         ("second.example.test", f"Bearer {rotated_key}", "model-B")]

        listed = read(client, PROFILES)
        assert "api_key" not in listed[0] and listed[0]["has_api_key"]
        stored = client.app.state.research.store.load_model_settings()
        for serialized in (json.dumps(stored), json.dumps(listed), first_probe.text, denied.text, duplicate.text):
            assert original_key not in serialized and rotated_key not in serialized

    with TestClient(create_app(tmp_path)) as client:
        stub_upstream(client, handler)
        assert client.post(f"{endpoint}/test").json()["data"]["ok"]
        assert calls[-1] == ("second.example.test", f"Bearer {rotated_key}", "model-B")


def test_running_and_future_runs_use_their_own_profile_snapshots(tmp_path):
    first_call, release_first = Event(), Event()
    observed = []

    def handler(request):
        prompt = json.loads(request.content)
        ctx = json.loads(prompt["messages"][1]["content"])
        observed.append((ctx["agent_id"], request.headers["authorization"], prompt["model"]))
        if not first_call.is_set():
            first_call.set()
            assert release_first.wait(timeout=5)
        fact = ctx["evidence_registry"][-1]
        return response(output(agent_id=ctx["agent_id"], decision="NEED_MORE_INFORMATION",
                               evidence_ids=[fact["evidence_id"]],
                               claims=[{key: fact[key] for key in ("fact_key", "value", "evidence_id")}],
                               missing_information=ctx["missing_information"]))

    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        stub_upstream(client, handler)
        first = create_profile(client, "基线", model="baseline-v1", api_key="fixture-profile-original")
        second = create_profile(client, "下一轮", model="comparison", api_key="fixture-profile-next")
        activate(client, first, "default")
        run_id = start(client, mode="llm")
        try:
            assert first_call.wait(timeout=5)
            changed = client.put(f"{PROFILES}/{first}", json={
                "name": "改名", **config(model="baseline-v2", api_key="fixture-profile-edited")})
            assert changed.status_code == 200
            assert read(client, DEFAULT)["model"] == "baseline-v2"
            activate(client, second, "default")
        finally:
            release_first.set()

        run = finish(client, run_id)
        assert run["status"] == "completed"
        assert set(observed) == {(role, "Bearer fixture-profile-original", "baseline-v1")
                                 for role in ("oncology", "radiology")}
        old_report = read(client, f"/api/v2/runs/{run_id}/report")
        assert old_report["model_configuration"] == run["model_configuration"]
        assert {(entry["profile_id"], entry["profile_name"], entry["model"]) for entry in
                run["model_configuration"]} == {(first, "基线", "baseline-v1")}
        observed.clear()
        next_run = finish(client, start(client, mode="llm"))
        assert next_run["status"] == "completed"
        assert {entry["profile_id"] for entry in next_run["model_configuration"]} == {second}
        assert set(observed) == {(role, "Bearer fixture-profile-next", "comparison") for role in ("oncology", "radiology")}
        assert read(client, f"/api/v2/runs/{run_id}/report") == old_report
        for surface in (run, old_report, read(client, f"/api/v2/runs/{run_id}/audit"), read(client, PROFILES)):
            assert "fixture-profile-" not in json.dumps(surface)
