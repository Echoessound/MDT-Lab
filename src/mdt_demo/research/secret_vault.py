"""Encrypt model credentials before persistence; the encryption key stays outside the database."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .provider_config import ProviderError


class SecretVault:
    def __init__(self, path: Path | None = None, *, key: str | bytes | None = None):
        from cryptography.fernet import Fernet

        key = key if key is not None else os.environ.get("MDT_SECRET_KEY")
        if key is None:
            if path is None:
                raise ProviderError("LLM_VAULT_KEY_REQUIRED", "持久保存模型配置需要独立的加密密钥。", 503)
            key = self._load_or_create(Path(path), Fernet.generate_key)
        try:
            self._fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)
        except (ValueError, TypeError, UnicodeError):
            raise ProviderError("LLM_VAULT_KEY_INVALID", "模型配置加密密钥无效；请检查 MDT_SECRET_KEY 或本地密钥文件。", 503) from None

    @staticmethod
    def _load_or_create(path: Path, generate_key) -> bytes:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(descriptor, "rb") as stream:
                    return stream.read(1024).strip()
            else:
                key = generate_key()
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(key + b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                return key
        except OSError:
            raise ProviderError("LLM_VAULT_UNAVAILABLE", "无法读取或创建模型配置加密密钥，请检查本地密钥文件权限。", 503) from None

    def encrypt(self, value: str, *, context: str) -> str:
        payload = json.dumps({"context": context, "secret": value}, ensure_ascii=False).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt(self, value: str, *, context: str) -> str:
        from cryptography.fernet import InvalidToken

        try:
            payload = json.loads(self._fernet.decrypt(value.encode("ascii")))
            if payload.get("context") != context or not isinstance(payload.get("secret"), str):
                raise ValueError("invalid binding")
            return payload["secret"]
        except (InvalidToken, UnicodeError, ValueError, TypeError, AttributeError):
            raise ProviderError("LLM_VAULT_DECRYPT_FAILED", "无法解密已保存的模型配置；请恢复原加密密钥，原配置未被覆盖。", 503) from None
