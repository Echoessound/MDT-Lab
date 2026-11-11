"""Local run service: bounded workers, durable snapshots, replay and cancellation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import re
from threading import Event, RLock
from uuid import uuid4

from pydantic import ValidationError

from .agents import demo_case
from .api_schemas import APIError, CreateRun, RunEvent, RunSnapshot
from .orchestrator import MDTOrchestrator, RunCancelled
from .scenarios import mock_agents
from .schemas import AgentOpinion, AuditEvent, MDTReport, Role, Stage, SyntheticCase

TERMINAL = {"completed", "incomplete", "failed", "cancelled"}
EVENT_TYPES = {
    "state_transition": "run.stage_changed", "case_loaded": "run.started",
    "agent_started": "agent.started", "agent_completed": "agent.completed",
    "agent_failed": "agent.failed", "disagreement_detected": "disagreement.detected",
    "discussion_started": "discussion.started", "discussion_finished": "discussion.completed",
    "report_generated": "report.generated", "report_saved": "report.ready",
    "cancel_requested": "run.cancel_requested",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def envelope(event: AuditEvent, seq: int) -> RunEvent:
    event_type = EVENT_TYPES.get(event.event_type, event.event_type)
    if event.event_type == "run_finished":
        status = event.details.get("status")
        event_type = "run.cancelled" if status == "cancelled" else (
            "run.failed" if status in {"failed", "rejected"} else "run.completed"
        )
    if event.event_type == "agent_completed" and event.stage == Stage.TARGETED_DISCUSSION:
        event_type = "discussion.agent_updated"
    return RunEvent(seq=seq, run_id=event.run_id, timestamp=event.timestamp,
                    type=event_type, payload=event)


class RunHandle:
    def __init__(self, snapshot: RunSnapshot) -> None:
        self.snapshot = snapshot
        self.events: list[RunEvent] = []
        self.cancel = Event()


class RunManager:
    def __init__(self, output_dir: Path, *, event_delay: float = 0.22) -> None:
        self.output_dir = output_dir.resolve()
        self.event_delay = max(0, min(event_delay, 2))
        self.cases = {"SYN-001": demo_case()}
        self._lock = RLock()
        self._handles: dict[str, RunHandle] = {}
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mdt")
        self._restore()

    def _persist(self, handle: RunHandle) -> None:
        folder = self.output_dir / handle.snapshot.run_id
        if folder.is_dir():
            temporary = folder / "snapshot.json.tmp"
            temporary.write_text(handle.snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.replace(folder / "snapshot.json")

    def _restore(self) -> None:
        if not self.output_dir.exists():
            return
        for folder in self.output_dir.iterdir():
            if not folder.is_dir() or not re.fullmatch(r"run_[0-9a-f]{32}", folder.name):
                continue
            try:
                raw_events = [AuditEvent.model_validate_json(line) for line in
                              (folder / "audit.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
                report_path = folder / "report.json"
                report = MDTReport.model_validate_json(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
                snapshot_path = folder / "snapshot.json"
                if snapshot_path.exists():
                    snapshot = RunSnapshot.model_validate_json(snapshot_path.read_text(encoding="utf-8"))
                elif report is not None:
                    snapshot = RunSnapshot(
                        run_id=report.run_id, case_id=report.case_id, mode=report.mode,
                        status=report.status, stage=Stage.SAVE_OUTPUT,
                        created_at=raw_events[0].timestamp, updated_at=raw_events[-1].timestamp,
                        report_ready=True, discussion_triggered=report.discussion_triggered,
                    )
                else:
                    continue
                if snapshot.run_id != folder.name or any(event.run_id != folder.name for event in raw_events):
                    continue
                handle = RunHandle(snapshot)
                self._handles[snapshot.run_id] = handle
                for event in raw_events:
                    self._consume(handle, event, persist=False)
                if report is not None:
                    snapshot.report_ready = True
                    for opinion in report.final_opinions:
                        snapshot.agents[opinion.agent_name].opinion = opinion
                        snapshot.agents[opinion.agent_name].status = "completed"
                    for record in report.discussion_records:
                        snapshot.agents[record.agent_name].previous_opinion = record.before
                if snapshot.status not in TERMINAL:
                    # A process restart cannot resume an old thread. Record the interruption honestly.
                    event = AuditEvent(
                        event_id=f"A{len(handle.events) + 1:04d}", run_id=snapshot.run_id,
                        timestamp=now(), stage=snapshot.stage, event_type="run_finished",
                        details={"status": "failed", "error_code": "process_interrupted"},
                    )
                    with (folder / "audit.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(event.model_dump_json() + "\n")
                    self._consume(handle, event)
            except (OSError, ValueError, IndexError, ValidationError):
                # One malformed historical directory must not prevent the service from starting.
                self._handles.pop(folder.name, None)

    def get_case(self, case_id: str) -> SyntheticCase:
        case = self.cases.get(case_id)
        if case is None:
            raise APIError(404, "CASE_NOT_FOUND", "未找到该合成病例。")
        return case.model_copy(deep=True)

    def _handle(self, run_id: str) -> RunHandle:
        handle = self._handles.get(run_id)
        if handle is None:
            raise APIError(404, "RUN_NOT_FOUND", "未找到该运行，请从病例工作台重新开始。")
        return handle

    def get(self, run_id: str) -> RunSnapshot:
        with self._lock:
            return self._handle(run_id).snapshot.model_copy(deep=True)

    def list_runs(self) -> list[RunSnapshot]:
        with self._lock:
            return [handle.snapshot.model_copy(deep=True) for handle in sorted(
                self._handles.values(), key=lambda handle: handle.snapshot.created_at, reverse=True,
            )[:100]]

    def start(self, request: CreateRun, *, source_run_id: str | None = None) -> RunSnapshot:
        case = self.get_case(request.case_id)
        if request.mode != "mock":
            raise APIError(409, "LLM_NOT_AVAILABLE", "本版本尚未接入真实模型，请选择离线 Mock。")
        with self._lock:
            if sum(handle.snapshot.status not in TERMINAL for handle in self._handles.values()) >= 4:
                raise APIError(429, "RUN_LIMIT", "已有四个待完成运行，请稍后重试。")
            snapshot = RunSnapshot(
                run_id=f"run_{uuid4().hex}", case_id=case.case_id, mode=request.mode,
                scenario=request.options.scenario, source_run_id=source_run_id,
                created_at=now(), updated_at=now(),
            )
            handle = RunHandle(snapshot)
            self._handles[snapshot.run_id] = handle
            self._pool.submit(self._execute, handle, case)
            return snapshot.model_copy(deep=True)

    def _consume(self, handle: RunHandle, event: AuditEvent, *, persist: bool = True) -> None:
        snapshot = handle.snapshot
        item = envelope(event, len(handle.events) + 1)
        handle.events.append(item)
        snapshot.last_seq = item.seq
        snapshot.updated_at = event.timestamp
        snapshot.stage = event.stage
        if snapshot.status == "queued":
            snapshot.status = "running"
        if event.agent_name is not None:
            agent = snapshot.agents[event.agent_name]
            if event.event_type == "agent_started":
                agent.status = "running"
            elif event.event_type == "agent_completed":
                if "opinion" in event.details:
                    if event.stage == Stage.TARGETED_DISCUSSION:
                        agent.previous_opinion = agent.opinion
                    agent.opinion = AgentOpinion.model_validate(event.details["opinion"])
                agent.status = "completed"
            elif event.event_type == "agent_failed":
                agent.status = "failed"
                agent.error = str(event.details.get("error_code", "agent_exception"))
        if event.event_type == "disagreement_detected":
            snapshot.discussion_triggered = bool(event.details.get("has_disagreement"))
        elif event.event_type == "report_saved":
            snapshot.report_ready = True
        elif event.event_type == "run_finished":
            status = event.details.get("status", "failed")
            snapshot.status = status if status in TERMINAL else "failed"
            for agent in snapshot.agents.values():
                if agent.status == "running":
                    agent.status = "waiting" if snapshot.status == "cancelled" else "failed"
                    agent.error = "process_interrupted" if snapshot.status == "failed" else None
        if persist:
            self._persist(handle)

    def _execute(self, handle: RunHandle, case: SyntheticCase) -> None:
        def on_event(event: AuditEvent) -> None:
            with self._lock:
                self._consume(handle, event)
            if event.event_type in {"agent_started", "state_transition"}:
                handle.cancel.wait(self.event_delay)

        try:
            MDTOrchestrator(
                output_dir=self.output_dir, agents=mock_agents(handle.snapshot.scenario), on_event=on_event,
            ).run(case, run_id=handle.snapshot.run_id, cancel_event=handle.cancel)
        except RunCancelled:
            pass
        except Exception:
            # Do not expose arbitrary exception strings in browser or audit responses.
            with self._lock:
                snapshot = handle.snapshot
                folder = self.output_dir / snapshot.run_id
                folder.mkdir(parents=True, exist_ok=True)
                event = AuditEvent(
                    event_id=f"A{len(handle.events) + 1:04d}", run_id=snapshot.run_id,
                    timestamp=now(), stage=snapshot.stage, event_type="run_finished",
                    details={"status": "failed", "error_code": "runtime_error"},
                )
                with (folder / "audit.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(event.model_dump_json() + "\n")
                self._consume(handle, event)

    def events(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[RunEvent]:
        with self._lock:
            return [event.model_copy(deep=True) for event in self._handle(run_id).events[after_seq:after_seq + limit]]

    def cancel(self, run_id: str) -> RunSnapshot:
        with self._lock:
            handle = self._handle(run_id)
            if handle.snapshot.status in TERMINAL or handle.snapshot.stage == Stage.SAVE_OUTPUT:
                raise APIError(409, "RUN_NOT_CANCELLABLE", "运行已结束或正在保存结果，无法再停止。")
            handle.cancel.set()
            handle.snapshot.status = "cancel_requested"
            handle.snapshot.cancel_requested = True
            self._persist(handle)
            return handle.snapshot.model_copy(deep=True)

    def report(self, run_id: str) -> MDTReport:
        snapshot = self.get(run_id)
        if not snapshot.report_ready:
            raise APIError(409, "REPORT_NOT_READY", "报告尚未就绪；已停止的运行不生成成功报告。")
        try:
            return MDTReport.model_validate_json(
                (self.output_dir / snapshot.run_id / "report.json").read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError):
            raise APIError(500, "REPORT_UNREADABLE", "报告文件无法读取，请查看审计日志并重新运行。") from None

    def close(self) -> None:
        with self._lock:
            for handle in self._handles.values():
                if handle.snapshot.status not in TERMINAL:
                    handle.cancel.set()
        self._pool.shutdown(wait=True, cancel_futures=False)
