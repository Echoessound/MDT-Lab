"""Two-step local dataset upload: bounded preview, then atomic import."""
import asyncio

from fastapi import APIRouter, Query, Request

from ..api_schemas import APIError
from .datasets import CATALOG, MAX_UPLOAD_BYTES
from .downloads import download_dataset
from .import_service import ImportPreviews

router = APIRouter(prefix="/api/v2/datasets", tags=["外部研究数据导入"])


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
