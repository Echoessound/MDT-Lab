"""Model configuration endpoints; responses never contain credentials."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .provider_config import LLMConfigInput, ProviderError
from .schemas import Role

router = APIRouter(prefix="/api/v2/settings/llm", tags=["Shared model configuration"])
agents_router = APIRouter(prefix="/api/v2/settings/agents", tags=["Per-agent model configuration"])


class ProfileInput(LLMConfigInput):
    name: str = Field(min_length=1, max_length=80)

    def connection(self) -> LLMConfigInput:
        return LLMConfigInput.model_validate(self.model_dump(exclude={"name"}))


class ProfileScope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scope: Literal["default"] | Role


class ProfileFromScope(ProfileScope):
    name: str = Field(min_length=1, max_length=80)


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


@router.get("/profiles")
def profiles(request: Request):
    return {"data": request.app.state.research.settings.profiles()}


@router.post("/profiles", status_code=201)
def create_profile(body: ProfileInput, request: Request):
    return {"data": request.app.state.research.settings.save_profile(body.name, body.connection())}


@router.post("/profiles/from-scope", status_code=201)
def profile_from_scope(body: ProfileFromScope, request: Request):
    return {"data": request.app.state.research.settings.profile_from_scope(body.scope, body.name)}


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: str, body: ProfileInput, request: Request):
    return {"data": request.app.state.research.settings.save_profile(body.name, body.connection(), profile_id=profile_id)}


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: str, request: Request):
    return {"data": request.app.state.research.settings.delete_profile(profile_id)}


@router.post("/profiles/{profile_id}/activate")
def activate_profile(profile_id: str, body: ProfileScope, request: Request):
    return {"data": request.app.state.research.settings.activate_profile(profile_id, body.scope)}


@router.post("/profiles/{profile_id}/test")
def test_profile(profile_id: str, request: Request):
    return {"data": request.app.state.research.settings.test_profile(profile_id)}


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
