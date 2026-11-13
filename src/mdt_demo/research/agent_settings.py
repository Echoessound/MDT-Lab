"""Model configuration service with per-agent overrides and a storage-independent secret boundary."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Protocol, TYPE_CHECKING

from pydantic import SecretStr, ValidationError

from .provider_config import LLMConfigInput, ProviderError, resolve_addresses
from .schemas import ROLES

if TYPE_CHECKING:
    from .provider import RunLLM
    from .secret_vault import SecretVault


class ModelSettingsRepository(Protocol):
    def load_model_settings(self) -> dict: ...
    def save_model_setting(self, key: str, value: dict) -> None: ...
    def delete_model_setting(self, key: str) -> None: ...


def _public(config: LLMConfigInput | None) -> dict:
    if config is None:
        return {"provider": "openai-compatible", "base_url": "https://api.openai.com/v1", "model": "",
                "has_api_key": False, "configured": False, "timeout_seconds": 20,
                "temperature": 0, "max_output_tokens": 1200}
    result = config.model_dump(exclude={"api_key"})
    result.update(has_api_key=bool(config.api_key and config.api_key.get_secret_value()), configured=True)
    return result


def _role(agent_id: str) -> str:
    if agent_id not in ROLES:
        raise ProviderError("AGENT_NOT_FOUND", "未找到该专科 Agent。", 404)
    return agent_id


class RunLLMGroup:
    """Dispatch only to providers frozen for this run, with aggregate factual usage."""
    def __init__(self, generators: dict[str, RunLLM], configurations: list[dict]):
        self._generators = dict(generators)
        self._configurations = deepcopy(configurations)

    def __call__(self, context: dict) -> dict:
        generator = self._generators.get(context.get("agent_id"))
        if generator is None:
            raise ProviderError("LLM_NOT_CONFIGURED", "此 Agent 未包含在本次冻结的模型配置中。", 409)
        return generator(context)

    @property
    def configuration_snapshot(self) -> list[dict]:
        return deepcopy(self._configurations)

    @property
    def metrics(self) -> dict:
        used = [generator.metrics for generator in self._generators.values() if generator.metrics["llm_calls"]]
        return {
            "llm_calls": sum(item["llm_calls"] for item in used),
            "retry_count": sum(item["retry_count"] for item in used),
            "prompt_tokens": sum(item["prompt_tokens"] for item in used) if used and all(item["prompt_tokens"] is not None for item in used) else None,
            "completion_tokens": sum(item["completion_tokens"] for item in used) if used and all(item["completion_tokens"] is not None for item in used) else None,
        }


class SettingsService:
    def __init__(self, *, transport=None, resolver=resolve_addresses,
                 repository: ModelSettingsRepository | None = None, vault: SecretVault | None = None):
        if (repository is None) != (vault is None):
            raise ValueError("repository and vault must be supplied together")
        self._configs: dict[str, LLMConfigInput] = {}
        self._lock = RLock()
        self._transport, self._resolver = transport, resolver
        self._repository, self._vault = repository, vault
        if repository is not None:
            self._restore()

    @staticmethod
    def _agent_key(agent_id: str) -> str:
        return f"agent:{_role(agent_id)}"

    def _restore(self) -> None:
        try:
            records = self._repository.load_model_settings()
        except Exception:
            raise ProviderError("LLM_SETTINGS_STORAGE_ERROR", "无法读取已保存的模型配置。", 503) from None
        known_keys = {"default", *(f"agent:{role}" for role in ROLES)}
        restored = {}
        try:
            if not isinstance(records, dict) or not set(records) <= known_keys:
                raise ValueError("invalid settings keys")
            for key, record in records.items():
                if (not isinstance(record, dict) or record.get("schema_version") != 1
                        or not isinstance(record.get("config"), dict) or "api_key" in record["config"]):
                    raise ValueError("invalid persisted settings")
                secret = self._vault.decrypt(record["encrypted_api_key"], context=key)
                if not secret.strip():
                    raise ValueError("empty persisted key")
                restored[key] = LLMConfigInput.model_validate({**record["config"], "api_key": secret})
        except (ValueError, TypeError, KeyError, ValidationError):
            raise ProviderError("LLM_SETTINGS_INVALID", "已保存的模型配置不符合当前契约，原记录未被覆盖。", 503) from None
        self._configs = restored

    def _persist(self, key: str, config: LLMConfigInput | None) -> None:
        if self._repository is None:
            return
        try:
            if config is None:
                self._repository.delete_model_setting(key)
            else:
                self._repository.save_model_setting(key, {
                    "schema_version": 1,
                    "config": config.model_dump(mode="json", exclude={"api_key"}),
                    "encrypted_api_key": self._vault.encrypt(config.api_key.get_secret_value(), context=key),
                })
        except Exception:
            raise ProviderError("LLM_SETTINGS_STORAGE_ERROR", "无法保存模型配置；当前配置未改变，请检查数据库连接。", 503) from None

    def _configure(self, key: str, body: LLMConfigInput | dict) -> None:
        config = body if isinstance(body, LLMConfigInput) else LLMConfigInput.model_validate(body)
        secret = config.api_key.get_secret_value().strip() if config.api_key else ""
        previous = self._configs.get(key)
        if not secret:
            if previous is None or config.base_url != previous.base_url:
                raise ProviderError("LLM_KEY_REQUIRED", "首次配置此 Agent 或更换服务地址时必须重新填写密钥。", 422)
            config = config.model_copy(update={"api_key": previous.api_key})
        else:
            config = config.model_copy(update={"api_key": SecretStr(secret)})
        self._persist(key, config)
        self._configs[key] = config.model_copy(deep=True)

    def status(self) -> dict:
        with self._lock:
            return _public(self._configs.get("default"))

    def configure(self, body: LLMConfigInput | dict) -> dict:
        with self._lock:
            self._configure("default", body)
            return self.status()

    def clear(self) -> dict:
        """Delete only the shared default; explicit agent overrides remain intact."""
        with self._lock:
            self._persist("default", None)
            self._configs.pop("default", None)
            return self.status()

    def _effective(self, agent_id: str) -> tuple[LLMConfigInput | None, str]:
        override = self._configs.get(self._agent_key(agent_id))
        if override is not None:
            return override, "agent"
        default = self._configs.get("default")
        return default, "default" if default is not None else "unconfigured"

    def agent_status(self, agent_id: str) -> dict:
        with self._lock:
            config, source = self._effective(agent_id)
            return {**_public(config), "agent_id": agent_id, "configuration_source": source,
                    "overridden": source == "agent"}

    def agent_statuses(self) -> list[dict]:
        with self._lock:
            return [self.agent_status(role) for role in ROLES]

    def configure_agent(self, agent_id: str, body: LLMConfigInput | dict) -> dict:
        with self._lock:
            self._configure(self._agent_key(agent_id), body)
            return self.agent_status(agent_id)

    def clear_agent(self, agent_id: str) -> dict:
        with self._lock:
            key = self._agent_key(agent_id)
            self._persist(key, None)
            self._configs.pop(key, None)
            return self.agent_status(agent_id)

    def _generator(self, config: LLMConfigInput) -> RunLLM:
        from .provider import RunLLM
        return RunLLM(config, transport=self._transport, resolver=self._resolver)

    def make_generator(self, selected_agents: list[str] | tuple[str, ...] | None = None):
        with self._lock:
            if selected_agents is None:
                config = self._configs.get("default")
                if config is None:
                    raise ProviderError("LLM_NOT_CONFIGURED", "尚未配置真实模型，请先配置模型或选择 Mock。", 409)
                return self._generator(config)
            roles = list(dict.fromkeys(selected_agents))
            if not roles:
                raise ProviderError("LLM_NOT_CONFIGURED", "本次运行没有选择可用 Agent。", 409)
            configs = {role: self._effective(role) for role in roles}
            missing = [role for role, (config, _) in configs.items() if config is None]
            if missing:
                raise ProviderError("LLM_NOT_CONFIGURED", "以下参与 Agent 尚未配置模型：" + "、".join(missing), 409)
            generators = {role: self._generator(config) for role, (config, _) in configs.items()}
            snapshots = [{"agent_id": role, "configuration_source": source,
                          **config.model_dump(mode="json", exclude={"api_key"})}
                         for role, (config, source) in configs.items()]
            return RunLLMGroup(generators, snapshots)

    def test(self) -> dict:
        return self.make_generator().test()

    def test_agent(self, agent_id: str) -> dict:
        with self._lock:
            config, _ = self._effective(agent_id)
            if config is None:
                raise ProviderError("LLM_NOT_CONFIGURED", "此 Agent 尚未配置模型连接。", 409)
            generator = self._generator(config)
        return generator.test()

    def close(self) -> None:
        """Drop decrypted credentials from this service while preserving encrypted records."""
        with self._lock:
            self._configs.clear()
