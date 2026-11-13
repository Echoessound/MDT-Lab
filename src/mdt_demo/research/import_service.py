"""Bounded import previews independent of HTTP routes and database drivers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
import time
from uuid import uuid4

from ..api_schemas import APIError
from .datasets import prepare_import
from .persistence.contracts import ResearchRepository


class ImportPreviews:
    def __init__(self, store: ResearchRepository, *, ttl_seconds=900):
        self.store = store
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._items = {}

    def preview(self, source, raw, max_cases):
        prepared = prepare_import(source, raw, max_cases)
        with self._lock:
            self._items = {key: value for key, value in self._items.items() if value[0] > time.monotonic()}
            if len(self._items) >= 3:
                # Older previews are disposable; committed records never live here.
                self._items.pop(next(iter(self._items)))
            preview_id = f"preview_{uuid4().hex}"
            self._items[preview_id] = (time.monotonic() + self.ttl_seconds, prepared)
        return {**deepcopy(prepared.summary), "preview_id": preview_id,
                "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)).isoformat()}

    def commit(self, preview_id):
        with self._lock:
            item = self._items.get(preview_id)
            if item is None or item[0] <= time.monotonic():
                self._items.pop(preview_id, None)
                raise APIError(409, "IMPORT_PREVIEW_EXPIRED", "预检查已过期或服务已重启，请重新选择文件预检查。")
            prepared = item[1]
            if not prepared.cases:
                raise APIError(422, "NO_IMPORTABLE_CASES", "没有符合契约的病例，本次未写入数据。")
            return self.store.import_cases(prepared.cases, prepared.summary)

    def clear(self):
        with self._lock:
            self._items.clear()
