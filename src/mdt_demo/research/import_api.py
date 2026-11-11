"""Two-step local dataset upload: bounded preview, then atomic import."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import RLock
import time
from uuid import uuid4

from fastapi import APIRouter, Query, Request

from ..api_schemas import APIError
from .datasets import CATALOG, MAX_UPLOAD_BYTES, prepare_import
from .downloads import download_dataset

router = APIRouter(prefix="/api/v2/datasets", tags=["外部研究数据导入"])


class ImportPreviews:
    def __init__(self, store, *, ttl_seconds=900):
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


@router.get("")
def catalog(request: Request):
    return {"data": {"sources": list(CATALOG.values()), "max_upload_bytes": MAX_UPLOAD_BYTES,
                     "batches": request.app.state.research.store.import_history()}}


@router.post("/preview")
async def preview(request: Request, source: str, max_cases: int = Query(10, ge=1, le=50)):
    if source not in CATALOG:
        raise APIError(422, "UNSUPPORTED_DATASET", "请选择支持的数据格式。")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise APIError(413, "DATASET_SIZE_LIMIT", "文件超过20MB限制。")
    result = await asyncio.to_thread(request.app.state.research.imports.preview, source, bytes(raw), max_cases)
    return {"data": result}


@router.post("/import/{preview_id}")
def commit(preview_id: str, request: Request):
    return {"data": request.app.state.research.imports.commit(preview_id)}


@router.post("/connect")
async def connect(request: Request, source: str, max_cases: int = Query(10, ge=1, le=50)):
    raw = await asyncio.to_thread(download_dataset, source)
    result = await asyncio.to_thread(request.app.state.research.imports.preview, source, raw, max_cases)
    return {"data": result}


@router.get("/template")
def template():
    from fastapi.responses import Response
    from .seeds import seed_cases
    import json
    case = seed_cases()[0].model_dump(mode="json")
    case["case_id"] = "CUSTOM-RESEARCH-001"
    return Response(json.dumps({"cases": [case]}, ensure_ascii=False, indent=2),
                    media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="research_cases.json"'})
