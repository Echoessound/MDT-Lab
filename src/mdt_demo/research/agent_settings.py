"""Model configuration service with per-agent overrides and a storage-independent secret boundary."""
from __future__ import annotations

from copy import deepcopy
import re
from threading import RLock
from typing import Protocol, TYPE_CHECKING
from uuid import uuid4

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


def _profile_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= 80 or not name.isprintable():
        raise ProviderError("LLM_PROFILE_NAME_INVALID", "方案名称须为 1 至 80 个可显示字符。", 422)
    return name


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

    def usage_summary(self) -> dict:
        """Aggregate sanitized known token subtotals and covered requests across used specialists."""
        from .provider import KNOWN_USAGE_KEYS

        used = [generator.usage_summary() for generator in self._generators.values() if generator.metrics["llm_calls"]]
        return {key: sum(item[key] for item in used) for key in KNOWN_USAGE_KEYS}


class SettingsService:
    def __init__(self, *, transport=None, resolver=resolve_addresses,
                 repository: ModelSettingsRepository | None = None, vault: SecretVault | None = None):
        if (repository is None) != (vault is None):
            raise ValueError("repository and vault must be supplied together")
        self._configs: dict[str, LLMConfigInput] = {}
        self._profile_names: dict[str, str] = {}
        self._bindings: dict[str, str] = {}
        self._lock = RLock()
        self._transport, self._resolver = transport, resolver
        self._repository, self._vault = repository, vault
        if repository is not None:
            self._restore()

    @staticmethod
    def _agent_key(agent_id: str) -> str:
        return f"agent:{_role(agent_id)}"

    def _scope_key(self, scope: str) -> str:
        return "default" if scope == "default" else self._agent_key(scope)

    def _restore(self) -> None:
        try:
            records = self._repository.load_model_settings()
        except Exception:
            raise ProviderError("LLM_SETTINGS_STORAGE_ERROR", "无法读取已保存的模型配置。", 503) from None
        known_keys = {"default", *(f"agent:{role}" for role in ROLES)}
        restored = {}
        try:
            if not isinstance(records, dict):
                raise ValueError("invalid settings keys")
            for key, record in records.items():
                if not isinstance(record, dict):
                    raise ValueError("invalid settings record")
                version = record.get("schema_version")
                if key in known_keys and version == 2 and set(record) == {"schema_version", "profile_id"}:
                    self._bindings[key] = record["profile_id"]
                    continue
                is_profile = re.fullmatch(r"profile:(prf_[a-f0-9]{32})", key)
                if is_profile and version == 2:
                    name = record["name"]
                    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not name.isprintable():
                        raise ValueError("invalid profile name")
                    self._profile_names[is_profile[1]] = name.strip()
                elif key not in known_keys or version != 1:
                    raise ValueError("invalid settings key or version")
                config = record.get("config")
                if not isinstance(config, dict) or "api_key" in config:
                    raise ValueError("invalid persisted settings")
                context = f"{key}@{config['base_url']}" if is_profile else key
                secret = self._vault.decrypt(record["encrypted_api_key"], context=context)
                if not secret.strip():
                    raise ValueError("empty persisted key")
                restored[key] = LLMConfigInput.model_validate({**config, "api_key": secret})
            if not set(self._bindings.values()) <= self._profile_names.keys():
                raise ValueError("unknown profile binding")
        except (ValueError, TypeError, KeyError, ValidationError):
            raise ProviderError("LLM_SETTINGS_INVALID", "已保存的模型配置不符合当前契约，原记录未被覆盖。", 503) from None
        self._configs = restored

    def _persist(self, key: str, config: LLMConfigInput | None = None, *,
                 name: str | None = None, binding: str | None = None) -> None:
        if self._repository is None:
            return
        try:
            if binding is not None:
                self._repository.save_model_setting(key, {"schema_version": 2, "profile_id": binding})
            elif config is None:
                self._repository.delete_model_setting(key)
            else:
                self._repository.save_model_setting(key, {
                    **({"schema_version": 2, "name": name} if name is not None else {"schema_version": 1}),
                    "config": config.model_dump(mode="json", exclude={"api_key"}),
                    "encrypted_api_key": self._vault.encrypt(
                        config.api_key.get_secret_value(), context=f"{key}@{config.base_url}" if name is not None else key),
                })
        except Exception:
            raise ProviderError("LLM_SETTINGS_STORAGE_ERROR", "无法保存模型配置；当前配置未改变，请检查数据库连接。", 503) from None

    def _configure(self, key: str, body: LLMConfigInput | dict, *, name: str | None = None) -> None:
        config = body if isinstance(body, LLMConfigInput) else LLMConfigInput.model_validate(body)
        secret = config.api_key.get_secret_value().strip() if config.api_key else ""
        previous = self._configs.get(key)
        if not secret:
            if previous is None or config.base_url != previous.base_url:
                raise ProviderError("LLM_KEY_REQUIRED", "首次直配、新建方案或更换服务地址时必须填写密钥。", 422)
            config = config.model_copy(update={"api_key": previous.api_key})
        else:
            config = config.model_copy(update={"api_key": SecretStr(secret)})
        self._persist(key, config, name=name)
        self._configs[key] = config.model_copy(deep=True)
        self._bindings.pop(key, None)

    def _resolve(self, key: str) -> tuple[LLMConfigInput | None, dict]:
        profile_id = self._bindings.get(key)
        if profile_id is None:
            return self._configs.get(key), {}
        return self._configs[f"profile:{profile_id}"], {
            "profile_id": profile_id, "profile_name": self._profile_names[profile_id],
        }

    def status(self) -> dict:
        with self._lock:
            config, profile = self._resolve("default")
            return {**_public(config), **profile}

    def configure(self, body: LLMConfigInput | dict) -> dict:
        with self._lock:
            self._configure("default", body)
            return self.status()

    def clear(self) -> dict:
        """Delete only the shared default; explicit agent overrides remain intact."""
        with self._lock:
            self._persist("default", None)
            self._configs.pop("default", None)
            self._bindings.pop("default", None)
            return self.status()

    def _effective(self, agent_id: str) -> tuple[LLMConfigInput | None, str, dict]:
        override, profile = self._resolve(self._agent_key(agent_id))
        if override is not None:
            return override, "agent", profile
        default, profile = self._resolve("default")
        return default, "default" if default is not None else "unconfigured", profile

    def agent_status(self, agent_id: str) -> dict:
        with self._lock:
            config, source, profile = self._effective(agent_id)
            return {**_public(config), **profile, "agent_id": agent_id, "configuration_source": source,
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
            self._bindings.pop(key, None)
            return self.agent_status(agent_id)

    def _profile_config(self, profile_id: str) -> LLMConfigInput:
        if profile_id not in self._profile_names:
            raise ProviderError("LLM_PROFILE_NOT_FOUND", "未找到模型连接方案。", 404)
        return self._configs[f"profile:{profile_id}"]

    def _profile_status(self, profile_id: str) -> dict:
        config = self._profile_config(profile_id)
        return {"profile_id": profile_id, "name": self._profile_names[profile_id], **_public(config)}

    def profiles(self) -> list[dict]:
        with self._lock:
            return [self._profile_status(pid) for pid in sorted(
                self._profile_names, key=lambda pid: self._profile_names[pid].casefold())]

    def save_profile(self, name: str, body: LLMConfigInput | dict, *, profile_id: str | None = None) -> dict:
        with self._lock:
            if profile_id is not None:
                self._profile_config(profile_id)
            name = _profile_name(name)
            if any(other.casefold() == name.casefold() and pid != profile_id for pid, other in self._profile_names.items()):
                raise ProviderError("LLM_PROFILE_NAME_CONFLICT", "已有同名模型方案，请换一个名称。", 409)
            profile_id = profile_id or f"prf_{uuid4().hex}"
            self._configure(f"profile:{profile_id}", body, name=name)
            self._profile_names[profile_id] = name
            return self._profile_status(profile_id)

    def profile_from_scope(self, scope: str, name: str) -> dict:
        with self._lock:
            config = self._resolve("default")[0] if scope == "default" else self._effective(scope)[0]
            if config is None:
                raise ProviderError("LLM_NOT_CONFIGURED", "此范围尚无可保存的模型连接。", 409)
            return self.save_profile(name, config)

    def activate_profile(self, profile_id: str, scope: str) -> dict:
        with self._lock:
            self._profile_config(profile_id)
            key = self._scope_key(scope)
            self._persist(key, binding=profile_id)
            self._bindings[key] = profile_id
            self._configs.pop(key, None)
            return self.status() if scope == "default" else self.agent_status(scope)

    def delete_profile(self, profile_id: str) -> dict:
        with self._lock:
            self._profile_config(profile_id)
            if profile_id in self._bindings.values():
                raise ProviderError("LLM_PROFILE_IN_USE", "此方案仍在使用，请先切换或清除对应范围的连接。", 409)
            key = f"profile:{profile_id}"
            self._persist(key, None)
            del self._configs[key]
            del self._profile_names[profile_id]
            return {"profile_id": profile_id, "deleted": True}

    def test_profile(self, profile_id: str) -> dict:
        with self._lock:
            generator = self._generator(self._profile_config(profile_id))
        return generator.test()

    def _generator(self, config: LLMConfigInput) -> RunLLM:
        from .provider import RunLLM
        return RunLLM(config, transport=self._transport, resolver=self._resolver)

    def make_generator(self, selected_agents: list[str] | tuple[str, ...] | None = None):
        with self._lock:
            if selected_agents is None:
                config, _ = self._resolve("default")
                if config is None:
                    raise ProviderError("LLM_NOT_CONFIGURED", "尚未配置真实模型，请先配置模型或选择 Mock。", 409)
                return self._generator(config)
            roles = list(dict.fromkeys(selected_agents))
            if not roles:
                raise ProviderError("LLM_NOT_CONFIGURED", "本次运行没有选择可用 Agent。", 409)
            configs = {role: self._effective(role) for role in roles}
            missing = [role for role, (config, _, _) in configs.items() if config is None]
            if missing:
                raise ProviderError("LLM_NOT_CONFIGURED", "以下参与 Agent 尚未配置模型：" + "、".join(missing), 409)
            generators = {role: self._generator(config) for role, (config, _, _) in configs.items()}
            snapshots = [{"agent_id": role, "configuration_source": source, **profile,
                          **config.model_dump(mode="json", exclude={"api_key"})}
                         for role, (config, source, profile) in configs.items()]
            return RunLLMGroup(generators, snapshots)

    def test(self) -> dict:
        return self.make_generator().test()

    def test_agent(self, agent_id: str) -> dict:
        with self._lock:
            config, _, _ = self._effective(agent_id)
            if config is None:
                raise ProviderError("LLM_NOT_CONFIGURED", "此 Agent 尚未配置模型连接。", 409)
            generator = self._generator(config)
        return generator.test()

    def close(self) -> None:
        """Drop decrypted credentials from this service while preserving encrypted records."""
        with self._lock:
            self._configs.clear()
            self._profile_names.clear()
            self._bindings.clear()
