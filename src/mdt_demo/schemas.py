"""Input, output and audit contracts. Case-dependent checks require context."""

from datetime import date, datetime
from enum import StrEnum
import re
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel, ConfigDict, Field, StrictInt, ValidationInfo,
    field_validator, model_validator,
)

DISCLAIMER = "本报告仅用于合成病例的科研模拟，不构成真实医疗建议。"
Text = Annotated[str, Field(strict=True, min_length=1, max_length=4000)]
Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,80}$")]


class Decision(StrEnum):
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    NEED_MORE_INFORMATION = "NEED_MORE_INFORMATION"
    DEFER_DECISION = "DEFER_DECISION"


class Role(StrEnum):
    ONCOLOGY = "oncology"
    SURGERY = "surgery"
    RADIOLOGY = "radiology"


class Mode(StrEnum):
    MOCK = "mock"
    LLM = "llm"


class Stage(StrEnum):
    LOAD_CASE = "LOAD_CASE"
    INITIAL_REVIEW = "INITIAL_REVIEW"
    DETECT_DISAGREEMENT = "DETECT_DISAGREEMENT"
    TARGETED_DISCUSSION = "TARGETED_DISCUSSION"
    BUILD_REPORT = "BUILD_REPORT"
    SAVE_OUTPUT = "SAVE_OUTPUT"


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True,
        revalidate_instances="always",
    )


class Patient(Model):
    age: Annotated[StrictInt, Field(ge=0, le=120)]
    sex: Literal["female", "male", "other", "unknown"]


class TimelineEvent(Model):
    event_id: Identifier
    date: date
    type: Identifier
    description: Text

    @field_validator("date", mode="before")
    @classmethod
    def iso_date(cls, value: Any) -> Any:
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("date 必须为 YYYY-MM-DD 格式的合法日期")
        return value


class SyntheticCase(Model):
    case_id: Identifier
    is_synthetic: Literal[True]
    patient: Patient
    timeline: Annotated[list[TimelineEvent], Field(min_length=1, max_length=1000)]
    current_question: Text
    available_options: Annotated[list[Decision], Field(min_length=1, max_length=3)]

    @field_validator("is_synthetic", mode="before")
    @classmethod
    def synthetic_only(cls, value: Any) -> bool:
        if value is not True:
            raise ValueError("仅接受 is_synthetic=true 的完全虚构病例")
        return value

    @field_validator("timeline")
    @classmethod
    def unique_sorted_events(cls, events: list[TimelineEvent]) -> list[TimelineEvent]:
        ids = [event.event_id for event in events]
        if len(ids) != len(set(ids)):
            raise ValueError("病程事件 ID 不得重复")
        return sorted(events, key=lambda event: (event.date, event.event_id))

    @field_validator("available_options")
    @classmethod
    def unique_options(cls, options: list[Decision]) -> list[Decision]:
        if len(options) != len(set(options)):
            raise ValueError("available_options 不得重复")
        return options


class AgentOpinion(Model):
    agent_name: Role
    decision: Decision
    reasoning_summary: Text
    supporting_event_ids: Annotated[list[Identifier], Field(min_length=1)]
    missing_information: list[Text]
    confidence: Literal["low", "medium", "high"]

    @field_validator("supporting_event_ids")
    @classmethod
    def unique_references(cls, references: list[str]) -> list[str]:
        if len(references) != len(set(references)):
            raise ValueError("证据引用不得重复")
        return references

    @model_validator(mode="after")
    def check_case(self, info: ValidationInfo) -> Self:
        case = (info.context or {}).get("case")
        if case is not None:
            if self.decision not in case.available_options:
                raise ValueError("decision 不在当前病例 available_options 中")
            known_ids = {event.event_id for event in case.timeline}
            if not set(self.supporting_event_ids) <= known_ids:
                raise ValueError("supporting_event_ids 引用了不存在的病例事件")
        return self


def validate_opinion(value: Any, case: SyntheticCase, expected_role: Role) -> AgentOpinion:
    """Always revalidate at the trust boundary, including existing model instances."""
    payload = value.model_dump() if isinstance(value, AgentOpinion) else value
    opinion = AgentOpinion.model_validate(payload, context={"case": case})
    if opinion.agent_name != expected_role:
        raise ValueError("Agent 输出角色与调用角色不一致")
    return opinion


class DisagreementResult(Model):
    has_disagreement: bool
    sufficient_opinions: bool
    conflicting_agents: list[Role]
    conflicting_decisions: list[Decision]
    missing_agents: list[Role]
    discussion_topic: Text


class DiscussionRecord(Model):
    round: Literal[1] = 1
    agent_name: Role
    topic: Text
    before: AgentOpinion
    after: AgentOpinion | None
    changed: bool
    status: Literal["completed", "failed"]
    audit_event_id: Identifier


class MDTReport(Model):
    run_id: Identifier
    case_id: Identifier
    mode: Mode
    status: Literal["completed", "incomplete", "failed"]
    initial_opinions: list[AgentOpinion]
    discussion_triggered: bool
    discussion_rounds: Annotated[StrictInt, Field(ge=0, le=1)]
    discussion_records: list[DiscussionRecord]
    final_opinions: list[AgentOpinion]
    final_decision: Decision
    unresolved_disagreements: list[DisagreementResult]
    missing_information: list[Text]
    warnings: list[Text]
    disclaimer: Literal[DISCLAIMER] = DISCLAIMER
    case_sha256: str
    audit_file: Literal["audit.jsonl"] = "audit.jsonl"
    audit_event_ids: list[Identifier]


class AuditEvent(Model):
    event_id: Identifier
    run_id: Identifier
    timestamp: datetime
    stage: Stage
    event_type: Identifier
    agent_name: Role | None = None
    details: dict[str, Any]
