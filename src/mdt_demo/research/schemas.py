"""Strict contracts for the longitudinal, synthetic research workbench."""

from datetime import date
import re
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr,
    field_validator, model_validator,
)

from ..schemas import Decision, Patient

Identifier = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,80}$")]
FactKey = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=4000)]
Scalar = StrictBool | StrictInt | StrictFloat | StrictStr | None
Role = Literal["oncology", "radiology", "surgery", "pathology"]
ROLES: tuple[Role, ...] = ("oncology", "radiology", "surgery", "pathology")
EventType = Literal[
    "diagnosis", "imaging", "pathology", "molecular_test", "procedure", "treatment",
    "medication", "toxicity", "follow_up", "progression", "recurrence", "observation",
]
Mode = Literal["mock", "llm"]
Scenario = Literal["standard", "partial_failure", "persistent_disagreement", "invalid_evidence"]
Confidence = Literal["low", "medium", "high"]
DISCLAIMER = (
    "科研模拟系统，仅用于合成或合法公开研究数据上的算法实验，不构成医疗建议，"
    "不用于真实患者诊断、治疗、处方或临床处置。证据校验仅验证输入引用和事实一致性，"
    "不证明医学有效性。"
)


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, str_strip_whitespace=True,
        revalidate_instances="always", allow_inf_nan=False,
    )


class Provenance(Model):
    source_name: Text
    source_url: Text | None = None
    dataset_version: Text
    license: Text
    synthetic: StrictBool
    artifact_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    artifact_name: Text | None = None
    mapping_version: Text | None = None
    citation: Text | None = None


class ClinicalEvent(Model):
    event_id: Identifier
    occurred_at: date
    event_type: EventType
    title: Text
    facts: Annotated[dict[FactKey, Scalar], Field(min_length=1, max_length=80)]
    source: Text
    source_record_id: Identifier | None = None
    synthetic_extension: StrictBool
    confidence: Literal["source_record", "derived", "synthetic"]
    introduced_in_version: Annotated[StrictInt, Field(ge=1)] = 1
    original_timestamp: Text | None = None
    source_record_locator: Text | None = None
    source_fields: dict[FactKey, Text] = Field(default_factory=dict)
    time_note: Text | None = None

    @field_validator("occurred_at", mode="before")
    @classmethod
    def strict_date(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("occurred_at 必须为 YYYY-MM-DD 合法日期")
        return value

    @field_validator("facts")
    @classmethod
    def bounded_facts(cls, facts):
        if any(isinstance(value, str) and len(value) > 2000 for value in facts.values()):
            raise ValueError("单个事实文本不得超过 2000 字符")
        return facts

    @model_validator(mode="after")
    def generated_source_is_explicit(self) -> Self:
        if self.source == "research_scenario_generator" and (
            not self.synthetic_extension or self.confidence != "synthetic"
            or self.source_record_id is not None
        ):
            raise ValueError("自建场景必须保留合成扩展标记，不得伪装原始研究记录")
        return self


class UnplacedRecord(Model):
    record_id: Identifier
    title: Text
    facts: Annotated[dict[FactKey, Scalar], Field(min_length=1, max_length=80)]
    source: Text
    source_record_id: Identifier
    source_record_locator: Text
    source_fields: dict[FactKey, Text]
    exclusion_reason: Text = "来源未提供可验证的记录可用时间；不进入历史评议上下文。"


class ResearchCase(Model):
    case_id: Identifier
    title: Text
    disease: Text
    case_kind: Literal["synthetic", "public_research", "mixed"] = "synthetic"
    version: Annotated[StrictInt, Field(ge=1)] = 1
    patient: Patient
    current_question: Text
    timeline: Annotated[list[ClinicalEvent], Field(min_length=1, max_length=1000)]
    provenance: Annotated[list[Provenance], Field(min_length=1, max_length=100)]
    unplaced_records: Annotated[list[UnplacedRecord], Field(max_length=100)] = Field(default_factory=list)
    data_notes: Annotated[list[Text], Field(max_length=30)] = Field(default_factory=list)

    @field_validator("timeline")
    @classmethod
    def unique_sorted_events(cls, events):
        ids = [event.event_id for event in events]
        if len(ids) != len(set(ids)):
            raise ValueError("病程事件 ID 不得重复")
        return sorted(events, key=lambda event: (event.occurred_at, event.event_id))

    @model_validator(mode="after")
    def provenance_and_version(self) -> Self:
        sources = {record.source_name: record for record in self.provenance}
        if len(sources) != len(self.provenance):
            raise ValueError("每个病例来源只能对应一份版本声明")
        kinds = {record.synthetic for record in self.provenance}
        expected = "synthetic" if kinds == {True} else "public_research" if kinds == {False} else "mixed"
        if self.case_kind != expected:
            raise ValueError("病例类型必须与原始来源和合成扩展一致")
        for record in self.unplaced_records:
            if record.source not in sources:
                raise ValueError("未定位记录来源缺少 provenance")
        for event in self.timeline:
            if event.source not in sources:
                raise ValueError("事件来源缺少 provenance")
            if event.introduced_in_version > self.version:
                raise ValueError("事件不能来自未来病例版本")
        return self


class RunRequest(Model):
    case_id: Identifier
    case_version: Annotated[StrictInt, Field(ge=1)]
    trigger_event_id: Identifier
    mode: Mode = "mock"
    mock_scenario: Scenario = "standard"
    routing_mode: Literal["event", "fixed"] = "event"


class RoutingReason(Model):
    agent_id: Role
    rule_id: Text
    description: Text


class Routing(Model):
    strategy_version: Text
    trigger_event_id: Identifier
    selected_agents: Annotated[list[Role], Field(min_length=1)]
    skipped_agents: list[Role]
    reasons: list[RoutingReason]


class EvidenceRef(Model):
    evidence_id: Text
    event_id: Identifier
    fact_key: FactKey
    value: Scalar
    source_name: Text
    source_record_id: Identifier | None
    dataset_version: Text
    synthetic: StrictBool
    quote_or_fact: Text
    artifact_sha256: str | None = None
    source_record_locator: Text | None = None
    source_field: Text | None = None


class Claim(Model):
    fact_key: FactKey
    value: Scalar
    evidence_id: Text


class AgentOutput(Model):
    agent_id: Role
    decision: Decision
    summary: Text
    evidence_ids: Annotated[list[Text], Field(min_length=1, max_length=80)]
    claims: Annotated[list[Claim], Field(min_length=1, max_length=80)]
    missing_information: Annotated[list[Text], Field(max_length=80)]
    confidence: Confidence

    @model_validator(mode="after")
    def coherent_references(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("证据 ID 不得重复")
        if not {claim.evidence_id for claim in self.claims} <= set(self.evidence_ids):
            raise ValueError("每个结构化事实都必须引用意见的 evidence_ids")
        if len(self.missing_information) != len(set(self.missing_information)):
            raise ValueError("资料缺口不得重复")
        return self


class ModelInfo(Model):
    provider: Text
    model: Text
    prompt_version: Text
    attempts: Annotated[StrictInt, Field(ge=1, le=2)]
    prompt_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    completion_tokens: Annotated[StrictInt, Field(ge=0)] | None = None


class Opinion(AgentOutput):
    opinion_id: Identifier
    evidence_refs: list[EvidenceRef]
    model_info: ModelInfo


class Conflict(Model):
    conflict_id: Identifier
    dimension: Text
    agent_ids: list[Role]
    description: Text
    evidence_ids: list[Text]


class SafetyCheck(Model):
    code: Text
    status: Literal["passed", "warning", "blocked"]
    message: Text
    evidence_ids: list[Text] = Field(default_factory=list)


class Safety(Model):
    decision: Decision
    status: Literal["passed", "needs_information", "blocked"]
    checks: list[SafetyCheck]
    missing_information: list[Text]
    warnings: list[Text]


class Metrics(Model):
    agent_calls: Annotated[StrictInt, Field(ge=0)] = 0
    llm_calls: Annotated[StrictInt, Field(ge=0)] = 0
    tool_calls: Annotated[StrictInt, Field(ge=0)] = 0
    retry_count: Annotated[StrictInt, Field(ge=0)] = 0
    prompt_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    completion_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    elapsed_ms: Annotated[float, Field(ge=0)] = 0


class DiscussionRecord(Model):
    agent_id: Role
    before: Opinion
    after: Opinion | None
    changed: StrictBool


class Report(Model):
    run_id: Identifier
    case_id: Identifier
    case_version: Annotated[StrictInt, Field(ge=1)]
    trigger_event_id: Identifier
    mode: Mode
    mock_scenario: Scenario
    routing_mode: Literal["event", "fixed"]
    case_snapshot: ResearchCase
    routing: Routing
    evidence_registry: list[EvidenceRef]
    initial_opinions: list[Opinion]
    final_opinions: list[Opinion]
    conflicts: list[Conflict]
    unresolved_conflicts: list[Conflict]
    discussion_records: list[DiscussionRecord]
    discussion_rounds: Annotated[StrictInt, Field(ge=0, le=1)]
    safety: Safety
    final_decision: Decision
    status: Literal["completed", "incomplete", "failed"]
    metrics: Metrics
    disclaimer: Literal[DISCLAIMER] = DISCLAIMER

    @model_validator(mode="after")
    def report_matches_snapshot(self) -> Self:
        if self.case_id != self.case_snapshot.case_id or self.case_version != self.case_snapshot.version:
            raise ValueError("报告必须与冻结病例版本一致")
        if self.final_decision != self.safety.decision:
            raise ValueError("最终标签必须来自证据门控")
        if len({opinion.agent_id for opinion in self.final_opinions}) != len(self.final_opinions):
            raise ValueError("最终意见不得重复角色")
        if not {opinion.agent_id for opinion in self.final_opinions} <= set(self.routing.selected_agents):
            raise ValueError("最终意见只能来自被调度角色")
        return self
