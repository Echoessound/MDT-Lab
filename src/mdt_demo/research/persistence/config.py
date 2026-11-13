"""Explicit repository selection at the application composition boundary."""
from dataclasses import dataclass, field
import os
from pathlib import Path

from ...api_schemas import APIError
from .contracts import ResearchRepository

DEFAULT_MONGODB_URI = "mongodb://127.0.0.1:27018/?replicaSet=mdt-rs&directConnection=true"


@dataclass(frozen=True)
class StorageConfig:
    backend: str = "mongodb"
    uri: str = field(default=DEFAULT_MONGODB_URI, repr=False)
    database: str = "mdt_lab"

    @classmethod
    def from_env(cls):
        return cls(backend=os.getenv("MDT_STORAGE_BACKEND", "mongodb"),
                   uri=os.getenv("MDT_MONGODB_URI", DEFAULT_MONGODB_URI),
                   database=os.getenv("MDT_MONGODB_DATABASE", "mdt_lab"))


def create_repository(config: StorageConfig, output_dir: Path) -> ResearchRepository:
    if config.backend == "mongodb":
        from .mongo import MongoResearchStore
        return MongoResearchStore(config.uri, config.database)
    if config.backend == "sqlite":
        from ..store import ResearchStore
        return ResearchStore(output_dir / "research.sqlite3")
    raise APIError(422, "STORAGE_INVALID_BACKEND", "MDT_STORAGE_BACKEND 必须为 mongodb 或 sqlite。")
