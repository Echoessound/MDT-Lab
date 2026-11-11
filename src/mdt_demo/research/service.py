"""Bounded local workers over the research engine and durable SQLite records."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event, RLock
import time
from uuid import uuid4

from pydantic import ValidationError

from ..api_schemas import APIError
from .engine import execute, route_case, WorkflowCancelled, WorkflowError
from .provider import SettingsService
from .import_api import ImportPreviews
from .schemas import ResearchCase, RunRequest
from .seeds import seed_cases
from .store import ResearchStore, TERMINAL, utcnow

ROLES = ("oncology", "radiology", "surgery", "pathology")


def json_model(value) -> dict:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(value)


def empty_metrics() -> dict:
    return {"agent_calls": 0, "llm_calls": 0, "tool_calls": 0, "retry_count": 0,
            "prompt_tokens": None, "completion_tokens": None, "elapsed_ms": 0}


class ResearchService:
    def __init__(self, output_dir: Path, *, event_delay: float = 0.22,
                 run_timeout_seconds: float = 120, settings=None) -> None:
        self.store = ResearchStore(output_dir / "research.sqlite3")
        self.imports = ImportPreviews(self.store)
        self.settings = settings if settings is not None else SettingsService()
        self.event_delay = max(0, min(event_delay, 2))
        self.run_timeout_seconds = max(0.01, min(run_timeout_seconds, 600))
        self._lock = RLock()
        self._cancels: dict[str, Event] = {}
        self._closed = False
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="research-mdt")
        self.store.seed([json_model(case) for case in seed_cases()])
        for old in self.store.runs(active_only=True):
            self._emit(old["run_id"], "run.failed", "FAILED", {"error_code": "process_interrupted"})

    @staticmethod
    def _validate_case(value: dict) -> dict:
        return ResearchCase.model_validate(value).model_dump(mode="json")

    def cases(self) -> list[dict]:
        return self.store.cases()

    def case(self, case_id: str, version: int | None = None) -> dict:
        return self.store.case(case_id, version)

    def append_event(self, case_id: str, expected_version: int, event: dict) -> dict:
        try:
            return self.store.append_event(case_id, expected_version, event, self._validate_case)
        except ValidationError:
            raise APIError(422, "INVALID_CLINICAL_EVENT", "新增事件不符合病例契约，请检查日期、事件类型与事实字段。") from None

    def routing(self, case_id: str, trigger_event_id: str, version: int | None = None,
                routing_mode: str = "event") -> dict:
        case = ResearchCase.model_validate(self.store.case(case_id, version))
        if trigger_event_id not in {event.event_id for event in case.timeline}:
            raise APIError(404, "EVENT_NOT_FOUND", "该触发事件不属于所选病例版本。")
        return json_model(route_case(case, trigger_event_id, routing_mode))

    def runs(self) -> list[dict]:
        return self.store.runs()

    def run(self, run_id: str) -> dict:
        return self.store.run(run_id)

    def start(self, request: RunRequest, *, source_run_id: str | None = None) -> dict:
        payload = json_model(request)
        case = ResearchCase.model_validate(self.store.case(payload["case_id"], payload["case_version"]))
        if payload["trigger_event_id"] not in {event.event_id for event in case.timeline}:
            raise APIError(404, "EVENT_NOT_FOUND", "该触发事件不属于所选病例版本。")
        # Freeze provider configuration before accepting a run; later settings edits
        # must not change the model midway through one experiment.
        generator = self.settings.make_generator() if payload["mode"] == "llm" else None
        with self._lock:
            if self._closed:
                raise APIError(503, "SERVICE_STOPPING", "服务正在停止，请稍后重试。")
            if len(self.store.runs(active_only=True)) >= 4:
                raise APIError(429, "RUN_LIMIT", "已有四个未完成研究运行，请稍后重试。")
            now = utcnow()
            run_id = f"run_{uuid4().hex}"
            snapshot = {**payload, "run_id": run_id, "source_run_id": source_run_id,
                        "status": "queued", "stage": "QUEUED", "created_at": now,
                        "updated_at": now, "last_seq": 0, "routing": None,
                        "agents": [{"agent_id": role, "status": "idle", "opinion": None,
                                    "previous_opinion": None, "error": None} for role in ROLES],
                        "conflicts": [], "safety": None, "report_ready": False,
                        "cancel_requested": False, "completed_nodes": [], "running_nodes": [],
                        "pending_nodes": [], "metrics": empty_metrics(), "error": None}
            self.store.create_run(snapshot, payload, json_model(case))
            self._cancels[run_id] = Event()
            self._emit(run_id, "run.created", "QUEUED", {"case_version": payload["case_version"]})
            self._pool.submit(self._execute, run_id, case, request, generator)
            return self.store.run(run_id)

    @staticmethod
    def _update(snapshot: dict, event: dict) -> None:
        kind, data, role = event["type"], event["payload"], event["agent_id"]
        snapshot["stage"] = event["stage"]
        if kind == "run.started":
            snapshot["status"] = "running"
        elif kind == "routing.completed":
            snapshot["routing"] = deepcopy(data)
            for agent in snapshot["agents"]:
                agent["status"] = "queued" if agent["agent_id"] in data["selected_agents"] else "skipped"
        elif kind == "workflow.progress":
            for key in ("completed_nodes", "running_nodes", "pending_nodes"):
                if key in data:
                    snapshot[key] = list(data[key])
        elif kind == "agent.started":
            snapshot["metrics"]["agent_calls"] += 1
        elif kind == "tool.completed":
            snapshot["metrics"]["tool_calls"] += 1
        elif kind == "conflict.detected":
            snapshot["conflicts"] = deepcopy(data.get("conflicts", []))
        elif kind == "safety.completed":
            snapshot["safety"] = deepcopy(data)
        elif kind == "report.generated":
            snapshot["report_ready"] = True
            snapshot["metrics"] = deepcopy(data["metrics"])
        elif kind == "run.cancel_requested":
            snapshot["cancel_requested"] = True
            snapshot["status"] = "cancel_requested"
        elif kind in {"run.completed", "run.failed", "run.cancelled"}:
            snapshot["status"] = data.get("status", "completed") if kind == "run.completed" else kind.split(".")[1]
            snapshot["error"] = data.get("error_code")
            snapshot["metrics"].update(data.get("metrics", {}))
            snapshot["running_nodes"] = []
            if kind != "run.completed":
                for agent in snapshot["agents"]:
                    if agent["status"] == "running":
                        agent["status"] = "failed" if kind == "run.failed" else "idle"
                        agent["error"] = data.get("error_code")
        if role:
            agent = next((item for item in snapshot["agents"] if item["agent_id"] == role), None)
            if agent is not None:
                if kind == "agent.started":
                    agent["status"] = "running"
                elif kind == "agent.completed":
                    if data.get("phase") == "discussion":
                        agent["previous_opinion"] = agent["opinion"]
                    agent["opinion"] = deepcopy(data["opinion"])
                    agent["status"] = "completed"
                    agent["error"] = None
                elif kind == "agent.failed":
                    agent["status"] = "failed"
                    agent["error"] = data.get("error_code", "agent_error")

    def _emit(self, run_id: str, kind: str, stage: str, payload: dict,
              agent_id: str | None = None) -> dict:
        with self._lock:
            event, _ = self.store.append_audit(run_id, kind, stage, payload, agent_id, self._update)
            return event

    def _execute(self, run_id: str, case: ResearchCase, request: RunRequest, generator) -> None:
        started = time.monotonic()
        cancellation = self._cancels[run_id]
        timed_out = False

        def cancelled() -> bool:
            nonlocal timed_out
            timed_out = timed_out or time.monotonic() - started >= self.run_timeout_seconds
            return cancellation.is_set() or timed_out

        def emit(kind, stage, payload, agent_id=None):
            # Engine metadata must never prematurely make an unsaved report available.
            if kind in {"report.generated", "run.completed", "run.failed", "run.cancelled"}:
                return
            self._emit(run_id, kind, stage, json_model(payload), agent_id)
            if kind in {"workflow.stage_changed", "agent.started"}:
                cancellation.wait(self.event_delay)

        try:
            if cancelled():
                raise WorkflowCancelled()
            self._emit(run_id, "run.started", "INITIALIZING", {})
            report = json_model(execute(case, request, run_id, emit, cancelled, llm=generator))
            if cancelled():
                raise WorkflowCancelled()
            report["metrics"]["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            with self._lock:
                if cancelled():
                    raise WorkflowCancelled()
                self.store.complete(run_id, report, self._update)
        except WorkflowCancelled:
            metric_update = {**(generator.metrics if generator is not None else {}), "elapsed_ms": round((time.monotonic() - started) * 1000)}
            if timed_out:
                self._emit(run_id, "run.failed", "FAILED", {"error_code": "run_timeout", "metrics": metric_update})
            else:
                self._emit(run_id, "run.cancelled", "CANCELLED", {"metrics": metric_update})
        except WorkflowError as exc:
            self._emit(run_id, "run.failed", "FAILED", {"error_code": exc.code})
        except Exception:
            # Arbitrary provider exceptions may contain credentials or response bodies.
            self._emit(run_id, "run.failed", "FAILED", {"error_code": "workflow_error"})
        finally:
            with self._lock:
                self._cancels.pop(run_id, None)

    def cancel(self, run_id: str) -> dict:
        with self._lock:
            snapshot = self.store.run(run_id)
            if snapshot["status"] in TERMINAL or snapshot["report_ready"]:
                raise APIError(409, "RUN_NOT_CANCELLABLE", "运行已结束或报告已经保存，无法再停止。")
            if snapshot["cancel_requested"]:
                return snapshot
            cancellation = self._cancels.get(run_id)
            if cancellation is None:
                raise APIError(409, "RUN_NOT_CANCELLABLE", "该运行不再属于活动任务。")
            cancellation.set()
            self._emit(run_id, "run.cancel_requested", snapshot["stage"], {})
            return self.store.run(run_id)

    def rerun(self, run_id: str) -> dict:
        request, _ = self.store.run_input(run_id)
        return self.start(RunRequest.model_validate(request), source_run_id=run_id)

    def report(self, run_id: str) -> dict:
        return self.store.report(run_id)

    def events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> list[dict]:
        return self.store.events(run_id, after_seq, limit)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for cancellation in self._cancels.values():
                cancellation.set()
        self._pool.shutdown(wait=True, cancel_futures=False)
        self.settings.clear()
        self.imports.clear()
        self.store.close()
