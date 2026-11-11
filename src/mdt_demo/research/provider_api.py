"""Local settings endpoints; credentials exist only in SettingsService memory."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .provider import LLMConfigInput, ProviderError

router = APIRouter(prefix="/api/v2/settings/llm", tags=["Research model configuration"])


def provider_error(exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


@router.get("")
def status(request: Request):
    return {"data": request.app.state.research.settings.status()}


@router.put("")
def configure(body: LLMConfigInput, request: Request):
    try:
        return {"data": request.app.state.research.settings.configure(body)}
    except ProviderError as exc:
        return provider_error(exc)


@router.delete("")
def clear(request: Request):
    return {"data": request.app.state.research.settings.clear()}


@router.post("/test")
def test(request: Request):
    try:
        return {"data": request.app.state.research.settings.test()}
    except ProviderError as exc:
        return provider_error(exc)
