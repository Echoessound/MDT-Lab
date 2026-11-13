"""Model configuration endpoints; responses never contain credentials."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .provider_config import LLMConfigInput, ProviderError

router = APIRouter(prefix="/api/v2/settings/llm", tags=["Shared model configuration"])
agents_router = APIRouter(prefix="/api/v2/settings/agents", tags=["Per-agent model configuration"])


def provider_error(exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})


@router.get("")
def status(request: Request):
    return {"data": request.app.state.research.settings.status()}


@router.put("")
def configure(body: LLMConfigInput, request: Request):
    return {"data": request.app.state.research.settings.configure(body)}


@router.delete("")
def clear(request: Request):
    return {"data": request.app.state.research.settings.clear()}


@router.post("/test")
def test(request: Request):
    return {"data": request.app.state.research.settings.test()}


@agents_router.get("")
def agents_status(request: Request):
    return {"data": request.app.state.research.settings.agent_statuses()}


@agents_router.get("/{agent_id}")
def agent_status(agent_id: str, request: Request):
    return {"data": request.app.state.research.settings.agent_status(agent_id)}


@agents_router.put("/{agent_id}")
def configure_agent(agent_id: str, body: LLMConfigInput, request: Request):
    return {"data": request.app.state.research.settings.configure_agent(agent_id, body)}


@agents_router.delete("/{agent_id}")
def clear_agent(agent_id: str, request: Request):
    return {"data": request.app.state.research.settings.clear_agent(agent_id)}


@agents_router.post("/{agent_id}/test")
def test_agent(agent_id: str, request: Request):
    return {"data": request.app.state.research.settings.test_agent(agent_id)}
