"""Append-only JSONL audit writer; callers supply structured, non-secret details."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from .schemas import AuditEvent, Role, Stage


class AuditLogger:
    def __init__(self, path: Path, run_id: str, on_event: Callable[[AuditEvent], None] | None = None) -> None:
        self.run_id = run_id
        self.event_ids: list[str] = []
        self._file: TextIO = path.open("x", encoding="utf-8")
        self._on_event = on_event

    def __enter__(self) -> "AuditLogger":
        return self

    def __exit__(self, *_: Any) -> None:
        self._file.close()

    def log(
        self, stage: Stage, event_type: str, *, agent_name: Role | None = None,
        **details: Any,
    ) -> str:
        event_id = f"A{len(self.event_ids) + 1:04d}"
        event = AuditEvent(
            event_id=event_id, run_id=self.run_id,
            timestamp=datetime.now(timezone.utc), stage=stage,
            event_type=event_type, agent_name=agent_name, details=details,
        )
        self._file.write(event.model_dump_json() + "\n")
        self._file.flush()
        self.event_ids.append(event_id)
        if self._on_event is not None:
            self._on_event(event.model_copy(deep=True))
        return event_id
