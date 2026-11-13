"""Shared provider contracts and URL validation, independent of storage and HTTP execution."""

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

class ProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502, *, attempts: int = 0):
        super().__init__(code)
        self.code, self.message, self.status_code, self.attempts = code, message, status_code, attempts


def canonical_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname
        _ = parsed.port
    except ValueError:
        raise ValueError("模型服务地址格式无效") from None
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError("模型服务必须使用不含账号、查询参数或片段的 HTTPS 地址")
    host = host.lower().rstrip(".")
    if host == "localhost" or "." not in host or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("模型服务不允许使用本机或内网地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global or address.is_multicast:
            raise ValueError("模型服务不允许使用本机或内网地址")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


class LLMConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = Field(min_length=1, max_length=160)
    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=20, ge=1, le=60)
    temperature: float = Field(default=0, ge=0, le=2)
    max_output_tokens: int = Field(default=1200, ge=128, le=8192)

    @field_validator("provider")
    @classmethod
    def supported_provider(cls, value):
        if value != "openai-compatible":
            raise ValueError("当前支持 openai-compatible 接口")
        return value

    @field_validator("base_url")
    @classmethod
    def secure_url(cls, value):
        return canonical_url(value)

    @field_validator("api_key")
    @classmethod
    def bounded_key(cls, value):
        if value is not None:
            secret = value.get_secret_value()
            if len(secret) > 1024 or any(char in secret for char in "\r\n\x00"):
                raise ValueError("密钥格式无效")
        return value


def resolve_addresses(host: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
