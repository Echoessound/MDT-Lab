"""Browser contracts, kept separate from the original CLI/report contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .scenarios import Scenario
from .schemas import AgentOpinion, AuditEvent, Mode, Role, Stage

RunStatus = Literal["queued", "running", "cancel_requested", "cancelled", "completed", "incomplete", "failed"]


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_discussion_rounds: Literal[1] = 1
    scenario: Scenario = "standard"


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    mode: Mode = Mode.MOCK
    options: RunOptions = Field(default_factory=RunOptions)


class AgentSnapshot(BaseModel):
    status: Literal["waiting", "running", "completed", "failed"] = "waiting"
    opinion: AgentOpinion | None = None
    previous_opinion: AgentOpinion | None = None
    error: str | None = None


class RunSnapshot(BaseModel):
    run_id: str
    case_id: str
    mode: Mode
    scenario: Scenario = "standard"
    source_run_id: str | None = None
    status: RunStatus = "queued"
    stage: Stage = Stage.LOAD_CASE
    created_at: datetime
    updated_at: datetime
    agents: dict[Role, AgentSnapshot] = Field(default_factory=lambda: {role: AgentSnapshot() for role in Role})
    discussion_triggered: bool = False
    cancel_requested: bool = False
    report_ready: bool = False
    last_seq: int = 0


class RunEvent(BaseModel):
    schema_version: Literal["1"] = "1"
    seq: int = Field(ge=1)
    run_id: str
    timestamp: datetime
    type: str
    payload: AuditEvent


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
