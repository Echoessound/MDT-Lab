"""Explicit, finite MDT workflow with isolation at every agent boundary."""

import hashlib
import json
import re
from pathlib import Path
from threading import Event
from typing import Any, Callable, Sequence
from uuid import uuid4

from pydantic import ValidationError

from .agents import Agent, OncologyAgent, RadiologyAgent, SurgeryAgent, UnsupportedCaseError
from .audit import AuditLogger
from .disagreement import detect_disagreement
from .llm import LLMNotImplementedError
from .report import build_report
from .schemas import (
    AgentOpinion, AuditEvent, DiscussionRecord, MDTReport, Mode, Role, Stage, SyntheticCase,
    validate_opinion,
)


class RunCancelled(Exception):
    """Cooperative cancellation at a workflow boundary; never a successful report."""


class MDTOrchestrator:
    def __init__(
        self, *, output_dir: str | Path = "outputs", mode: Mode | str = Mode.MOCK,
        agents: Sequence[Agent] | None = None,
        on_event: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self.mode = Mode(mode)
        if self.mode == Mode.LLM:
            raise LLMNotImplementedError()
        self.output_dir = Path(output_dir)
        self.on_event = on_event
        self.agents = tuple(agents) if agents is not None else (
            OncologyAgent(), SurgeryAgent(), RadiologyAgent(),
        )
        names = [agent.name for agent in self.agents]
        if len(names) != len(Role) or set(names) != set(Role):
            raise ValueError("必须各配置一个 oncology、surgery 和 radiology Agent")

    def run(
        self, case: SyntheticCase | dict[str, Any], *, run_id: str | None = None,
        cancel_event: Event | None = None,
    ) -> MDTReport:
        run_id = run_id or f"run_{uuid4().hex}"
        if not re.fullmatch(r"run_[0-9a-f]{32}", run_id):
            raise ValueError("run_id 必须是 run_ 加 32 位十六进制字符")
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        with AuditLogger(run_dir / "audit.jsonl", run_id, self.on_event) as audit:
            stage: Stage | None = None

            def checkpoint(current_stage: Stage) -> None:
                if cancel_event is not None and cancel_event.is_set():
                    audit.log(current_stage, "cancel_requested", status="cancel_requested")
                    audit.log(current_stage, "run_finished", status="cancelled")
                    raise RunCancelled()

            def transition(next_stage: Stage) -> None:
                nonlocal stage
                checkpoint(stage or next_stage)
                previous = stage
                stage = next_stage
                audit.log(stage, "state_transition", previous=previous, current=stage)

            transition(Stage.LOAD_CASE)
            try:
                payload = case.model_dump() if isinstance(case, SyntheticCase) else case
                case = SyntheticCase.model_validate(payload)
            except ValidationError:
                audit.log(Stage.LOAD_CASE, "case_rejected", error_code="invalid_case")
                audit.log(Stage.LOAD_CASE, "run_finished", status="rejected")
                raise
            canonical = json.dumps(case.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            case_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            audit.log(Stage.LOAD_CASE, "case_loaded", case_id=case.case_id, case_sha256=case_hash)
            initial: list[AgentOpinion] = []
            errors: list[str] = []
            records: list[DiscussionRecord] = []

            def failure(exc: Exception, role: Role, current_stage: Stage) -> str:
                if isinstance(exc, UnsupportedCaseError):
                    code = "unsupported_case"
                elif isinstance(exc, (ValidationError, ValueError)):
                    code = "invalid_opinion"
                else:
                    code = "agent_exception"
                # Never serialize exception text: an adapter could put API keys in it.
                errors.append(f"{role.value}/{current_stage.value}: {code}")
                return audit.log(current_stage, "agent_failed", agent_name=role, error_code=code)

            transition(Stage.INITIAL_REVIEW)
            for agent in self.agents:
                role = Role(agent.name)
                audit.log(Stage.INITIAL_REVIEW, "agent_started", agent_name=role)
                checkpoint(Stage.INITIAL_REVIEW)
                try:
                    raw = agent.initial_review(case.model_copy(deep=True))
                    opinion = validate_opinion(raw, case, role)
                except Exception as exc:
                    failure(exc, role, Stage.INITIAL_REVIEW)
                else:
                    initial.append(opinion)
                    audit.log(Stage.INITIAL_REVIEW, "agent_completed", agent_name=role,
                              decision=opinion.decision, supporting_event_ids=opinion.supporting_event_ids,
                              opinion=opinion.model_dump(mode="json"))

            transition(Stage.DETECT_DISAGREEMENT)
            disagreement = detect_disagreement(initial)
            audit.log(Stage.DETECT_DISAGREEMENT, "disagreement_detected",
                      **disagreement.model_dump(mode="json"))
            final_by_role = {opinion.agent_name: opinion for opinion in initial}
            if disagreement.has_disagreement:
                transition(Stage.TARGETED_DISCUSSION)
                audit.log(Stage.TARGETED_DISCUSSION, "discussion_started", round=1,
                          topic=disagreement.discussion_topic)
                # Everyone gets the same initial snapshot; no within-round information leakage.
                for agent in self.agents:
                    role = Role(agent.name)
                    before = final_by_role.get(role)
                    if before is None:
                        continue
                    audit.log(Stage.TARGETED_DISCUSSION, "agent_started", agent_name=role)
                    checkpoint(Stage.TARGETED_DISCUSSION)
                    try:
                        raw = agent.discuss(
                            case.model_copy(deep=True),
                            tuple(opinion.model_copy(deep=True) for opinion in initial),
                            disagreement.model_copy(deep=True),
                        )
                        after = validate_opinion(raw, case, role)
                    except Exception as exc:
                        event_id = failure(exc, role, Stage.TARGETED_DISCUSSION)
                        # The prior opinion stays in history, not among valid final outputs.
                        final_by_role.pop(role)
                        after = None
                    else:
                        final_by_role[role] = after
                        event_id = audit.log(
                            Stage.TARGETED_DISCUSSION, "agent_completed", agent_name=role,
                            decision=after.decision, supporting_event_ids=after.supporting_event_ids,
                            opinion=after.model_dump(mode="json"), before=before.model_dump(mode="json"),
                        )
                    records.append(DiscussionRecord(
                        agent_name=role, topic=disagreement.discussion_topic, before=before,
                        after=after, changed=after != before if after else False,
                        status="completed" if after else "failed", audit_event_id=event_id,
                    ))
                audit.log(Stage.TARGETED_DISCUSSION, "discussion_finished", round=1)

            final = [final_by_role[role] for role in Role if role in final_by_role]
            transition(Stage.BUILD_REPORT)
            report = build_report(
                run_id=run_id, case=case, case_sha256=case_hash, mode=self.mode,
                initial_opinions=initial, final_opinions=final, discussion_records=records,
                discussion_triggered=disagreement.has_disagreement,
                errors=errors, audit_event_ids=[],
            )
            audit.log(Stage.BUILD_REPORT, "report_generated", final_decision=report.final_decision,
                      status=report.status)
            transition(Stage.SAVE_OUTPUT)
            report = report.model_copy(update={"audit_event_ids": audit.event_ids.copy()})
            # Rename a complete temporary file so a partial report is never presented as valid.
            temporary = run_dir / "report.json.tmp"
            temporary.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.replace(run_dir / "report.json")
            audit.log(Stage.SAVE_OUTPUT, "report_saved", report_file="report.json")
            audit.log(Stage.SAVE_OUTPUT, "run_finished", status=report.status, report_file="report.json")
            return report
