"""Independent role routing and encrypted restart recovery, without paid calls."""
import json
import stat

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from mdt_demo.api import create_app
from mdt_demo.research.agent_settings import SettingsService
from mdt_demo.research.provider_config import ProviderError
from mdt_demo.research.secret_vault import SecretVault
from mdt_demo.research.store import ResearchStore
from test_research_provider import config, context, output, response
from test_research_api import finish, start


def test_role_overrides_fallback_and_frozen_dispatch_are_isolated():
    captured = []
    def upstream(request):
        data = json.loads(request.content)
        role = json.loads(data["messages"][1]["content"])["agent_id"]
        captured.append((request.url.host, request.headers["authorization"], data["model"]))
        return response(output(agent_id=role))
    settings = SettingsService(transport=httpx.MockTransport(upstream), resolver=lambda _: ["93.184.216.34"])
    settings.configure(config())
    settings.configure_agent("radiology", config(base_url="https://radiology.example.test/v1", api_key="radiology-secret", model="radiology-model"))
    with pytest.raises(ProviderError, match="LLM_KEY_REQUIRED"):
        settings.configure_agent("surgery", config(api_key=""))
    frozen = settings.make_generator(["oncology", "radiology"])
    settings.configure_agent("radiology", config(api_key="new-secret", model="new-model"))
    settings.clear()
    assert not settings.agent_status("oncology")["configured"]
    assert settings.agent_status("radiology")["configuration_source"] == "agent"
    with pytest.raises(ProviderError, match="LLM_NOT_CONFIGURED"):
        settings.make_generator(["oncology", "radiology"])
    frozen(context())
    frozen({**context(), "agent_id": "radiology"})
    assert captured == [("api.example.test", "Bearer fixture-secret-never-return", "fixture-model"),
                        ("radiology.example.test", "Bearer radiology-secret", "radiology-model")]
    assert frozen.metrics["llm_calls"] == 2 and frozen.metrics["prompt_tokens"] == 42
    assert "secret" not in json.dumps(frozen.configuration_snapshot)
    assert "api_key" not in json.dumps(frozen.configuration_snapshot)
    with pytest.raises(ProviderError, match="LLM_NOT_CONFIGURED"):
        frozen({**context(), "agent_id": "surgery"})
    settings.configure(config())
    assert settings.clear_agent("radiology")["configuration_source"] == "default"


def test_encrypted_restart_requires_original_key_and_rejects_swapped_credentials(tmp_path):
    store = ResearchStore(tmp_path / "test.sqlite3")
    key_path = tmp_path / "vault.key"
    vault = SecretVault(key_path)
    settings = SettingsService(repository=store, vault=vault)
    settings.configure(config())
    settings.configure_agent("surgery", config(api_key="surgery-secret"))
    records = store.load_model_settings()
    serialized = json.dumps(records)
    assert "fixture-secret-never-return" not in serialized and "surgery-secret" not in serialized
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    settings.close()
    restored = SettingsService(repository=store, vault=SecretVault(key_path))
    assert restored.agent_status("surgery")["has_api_key"]
    assert restored.agent_status("pathology")["configuration_source"] == "default"
    with pytest.raises(ProviderError, match="LLM_VAULT_DECRYPT_FAILED"):
        SettingsService(repository=store, vault=SecretVault(key=Fernet.generate_key()))
    assert store.load_model_settings() == records
    store.save_model_setting("agent:surgery", records["default"])
    with pytest.raises(ProviderError, match="LLM_VAULT_DECRYPT_FAILED"):
        SettingsService(repository=store, vault=vault)
    store.close()


def test_storage_failure_does_not_change_active_settings(tmp_path, monkeypatch):
    store = ResearchStore(tmp_path / "test.sqlite3")
    settings = SettingsService(repository=store, vault=SecretVault(tmp_path / "key"))
    settings.configure(config())
    before = settings.status()
    def fail(*args):
        raise RuntimeError("secret debug must not escape")
    monkeypatch.setattr(store, "save_model_setting", fail)
    with pytest.raises(ProviderError, match="LLM_SETTINGS_STORAGE_ERROR") as error:
        settings.configure(config(model="replacement"))
    assert "secret debug" not in error.value.message
    assert settings.status() == before
    store.close()


def test_agent_api_persists_restarts_and_validates_roles(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/v2/storage").json()["data"]["backend"] == "sqlite"
        assert len(client.get("/api/v2/settings/agents").json()["data"]) == 4
        saved = client.put("/api/v2/settings/agents/radiology", json=config())
        assert saved.status_code == 200 and "fixture-secret" not in saved.text
        assert client.get("/api/v2/settings/agents/unknown").status_code == 404
        assert client.put("/api/v2/settings/agents/radiology", json=config(), headers={"Origin": "https://elsewhere.example"}).status_code == 403
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/v2/settings/agents/radiology").json()["data"]["configured"]
        assert not client.get("/api/v2/settings/agents/surgery").json()["data"]["configured"]
        assert not client.delete("/api/v2/settings/agents/radiology").json()["data"]["configured"]


def test_only_selected_agents_need_configuration_and_report_freezes_provenance(tmp_path):
    captured = []
    def upstream(request):
        prompt = json.loads(request.content)
        ctx = json.loads(prompt["messages"][1]["content"])
        captured.append((ctx["agent_id"], request.headers["authorization"], prompt["model"]))
        fact = ctx["evidence_registry"][-1]
        return response(output(agent_id=ctx["agent_id"], decision="NEED_MORE_INFORMATION",
            evidence_ids=[fact["evidence_id"]], claims=[{key: fact[key] for key in ("fact_key", "value", "evidence_id")}],
            missing_information=ctx["missing_information"]))
    with TestClient(create_app(tmp_path, event_delay=0)) as client:
        settings = client.app.state.research.settings
        settings._transport = httpx.MockTransport(upstream)
        settings._resolver = lambda _: ["93.184.216.34"]
        for role in ("oncology", "radiology"):
            settings.configure_agent(role, config(api_key=f"{role}-secret", model=f"{role}-model"))
        assert not settings.status()["configured"]
        run_id = start(client, mode="llm")
        run = finish(client, run_id)
        assert run["status"] == "completed"
        assert set(captured) == {("oncology", "Bearer oncology-secret", "oncology-model"), ("radiology", "Bearer radiology-secret", "radiology-model")}
        report = client.get(f"/api/v2/runs/{run_id}/report").json()["data"]
        assert report["model_configuration"] == run["model_configuration"]
        assert [item["configuration_source"] for item in report["model_configuration"]] == ["agent", "agent"]
        assert "secret" not in json.dumps(report) + client.get(f"/api/v2/runs/{run_id}/audit").text
        settings.configure_agent("oncology", config(model="changed", api_key="changed-secret"))
        assert client.get(f"/api/v2/runs/{run_id}/report").json()["data"] == report
        rejected = client.post("/api/v2/runs", json={"case_id": "LUNG-SYN-001", "case_version": 1, "trigger_event_id": "E002", "mode": "llm", "routing_mode": "fixed"})
        assert rejected.status_code == 409
        assert len(client.get("/api/v2/runs").json()["data"]) == 1


def test_heterogeneous_group_retains_known_usage_subtotals_when_specialist_omits_usage():
    def upstream(request):
        data = json.loads(request.content)
        role = json.loads(data["messages"][1]["content"])["agent_id"]
        return response(output(agent_id=role), usage=(role == "oncology"))

    service = SettingsService(transport=httpx.MockTransport(upstream), resolver=lambda _: ["93.184.216.34"])
    service.configure(config())
    service.configure_agent("radiology", config(base_url="https://radiology.example.test/v1", api_key="rad-secret", model="rad-model"))
    frozen = service.make_generator(["oncology", "radiology", "surgery"])
    frozen(context())
    frozen({**context(), "agent_id": "radiology"})
    assert frozen.metrics == {
        "llm_calls": 2,
        "retry_count": 0,
        "prompt_tokens": None,
        "completion_tokens": None,
    }
    assert frozen.usage_summary() == {
        "known_prompt_tokens": 21,
        "known_completion_tokens": 13,
        "prompt_usage_requests": 1,
        "completion_usage_requests": 1,
    }
