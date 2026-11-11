"""Read only supported configuration; never include secrets in diagnostics."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

from .schemas import Mode


@dataclass(frozen=True)
class Settings:
    mode: Mode = Mode.MOCK
    output_dir: Path = Path("outputs")

    @classmethod
    def from_env(cls, mode: str | None = None, output_dir: Path = Path("outputs")) -> "Settings":
        load_dotenv(Path.cwd() / ".env", override=False)
        value = mode if mode is not None else os.getenv("MDT_MODE", "mock")
        try:
            resolved = Mode(value)
        except ValueError:
            raise ValueError("MDT_MODE 必须为 mock 或 llm") from None
        return cls(mode=resolved, output_dir=output_dir)
