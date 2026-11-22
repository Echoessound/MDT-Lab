"""Two-step local dataset upload: bounded preview, then atomic import."""
import asyncio

from fastapi import APIRouter, Query, Request

from ..api_schemas import APIError
from .datasets import CATALOG, DATA_CAPABILITIES, MAX_UPLOAD_BYTES
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


@router.get("/capabilities")
def capabilities():
    return {"data": DATA_CAPABILITIES}


@router.get("/template")
def template(source: str = Query("research_json")):
    from fastapi.responses import Response
    from .seeds import seed_cases
    import json
    if source == "tcga_cbioportal_tsv":
        sample_tsv = "\n".join([
            "#Patient Identifier\tDiagnosis Age\tSex\tDiagnosis Date\tPathology Date\tCancer Type Detailed\tPathological T stage\tPathological N stage\tPathological M stage\tEGFR_STATUS\tKRAS_STATUS\tOS_MONTHS\tOS_STATUS",
            "PATIENT_ID\tAGE\tSEX\tDIAGNOSIS_DATE\tPATHOLOGY_DATE\tHISTOLOGY\tPATH_T_STAGE\tPATH_N_STAGE\tPATH_M_STAGE\tEGFR_STATUS\tKRAS_STATUS\tOS_MONTHS\tOS_STATUS",
            "TCGA-LUAD-DEMO-01\t62\tFemale\t2024-03-10\t2024-03-15\tAdenocarcinoma\tT2a\tN1\tM0\tMutant\tWildtype\t14.5\t0:LIVING",
            "TCGA-LUSC-DEMO-02\t68\tMale\t2024-05-02\t2024-05-08\tSquamous cell carcinoma\tT3\tN2\tM0\tWildtype\tNot collected\t9.2\t0:LIVING",
        ]) + "\n"
        return Response(
            sample_tsv,
            media_type="text/tab-separated-values; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="tcga_luad_clinical_template.tsv"'},
        )
    case = seed_cases()[0].model_dump(mode="json")
    case["case_id"] = "CUSTOM-RESEARCH-001"
    return Response(json.dumps({"cases": [case]}, ensure_ascii=False, indent=2),
                    media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="research_cases.json"'})
