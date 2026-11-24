"""Bounded workers over a database-independent engine and repository contract."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event, RLock
import time
from uuid import uuid4

from pydantic import ValidationError

from ..api_schemas import APIError
from .adjudication import AdjudicationInput, MultiRaterStore, MultiRaterSubmissionInput
from .blind_review import review_material, validate_reference
from .engine import execute, route_case, WorkflowCancelled, WorkflowError
from .agent_settings import SettingsService
from .import_service import ImportPreviews
from .schemas import ResearchCase, RunRequest
from .seeds import seed_cases
from .store import ResearchStore, TERMINAL, utcnow
from .persistence.contracts import ResearchRepository
from .evaluation import AnnotationStore, BlindAnnotationInput, evaluate_library
from .media_store import MediaAttachmentStore
from .temporal_audit import audit_temporal_boundary
from .workflow_designer import (
    design_medical_workflow,
    evaluate_ablation_matrix,
    infer_semantic_completeness,
    process_case_imaging,
    semantic_extension,
)

ROLES = ("oncology", "radiology", "surgery", "pathology")


def json_model(value) -> dict:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else deepcopy(value)


def empty_metrics() -> dict:
    return {"agent_calls": 0, "llm_calls": 0, "tool_calls": 0, "retry_count": 0,
            "prompt_tokens": None, "completion_tokens": None, "elapsed_ms": 0}


class ResearchService:
    def __init__(self, output_dir: Path, *, event_delay: float = 0.22,
                 run_timeout_seconds: float = 120, settings=None,
                 store: ResearchRepository | None = None) -> None:
        self.store = store if store is not None else ResearchStore(output_dir / "research.sqlite3")
        self.imports = ImportPreviews(self.store)
        self.media = MediaAttachmentStore(output_dir / "media")
        self.annotations = AnnotationStore(output_dir / "annotations.json")
        self.review_panel = MultiRaterStore(output_dir / "multi_rater_reviews.json")
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

    def workflow_plan(self, case_id: str, trigger_event_id: str | None = None,
                      version: int | None = None) -> dict:
        case = ResearchCase.model_validate(self.store.case(case_id, version))
        if trigger_event_id and trigger_event_id not in {event.event_id for event in case.timeline}:
            raise APIError(404, "EVENT_NOT_FOUND", "该触发事件不属于所选病例版本。")
        return design_medical_workflow(case, trigger_event_id)

    def imaging_pipeline(self, case_id: str, trigger_event_id: str | None = None,
                         version: int | None = None) -> dict:
        case = ResearchCase.model_validate(self.store.case(case_id, version))
        if trigger_event_id and trigger_event_id not in {event.event_id for event in case.timeline}:
            raise APIError(404, "EVENT_NOT_FOUND", "该触发事件不属于所选病例版本。")
        return process_case_imaging(case, trigger_event_id)

    def ablation_matrix(self, case_id: str, trigger_event_id: str | None = None,
                        version: int | None = None) -> dict:
        case = ResearchCase.model_validate(self.store.case(case_id, version))
        if trigger_event_id and trigger_event_id not in {event.event_id for event in case.timeline}:
            raise APIError(404, "EVENT_NOT_FOUND", "该触发事件不属于所选病例版本。")
        return evaluate_ablation_matrix(case, trigger_event_id)

    def auto_enrich_case(self, case_id: str, expected_version: int,
                         trigger_event_id: str | None = None) -> dict:
        case = ResearchCase.model_validate(self.store.case(case_id))
        if case.version != expected_version:
            raise APIError(409, "CASE_VERSION_CONFLICT", "病例已更新，请刷新后重新执行智能补齐。")
        if trigger_event_id and trigger_event_id not in {event.event_id for event in case.timeline}:
            raise APIError(404, "EVENT_NOT_FOUND", "该触发事件不属于所选病例版本。")
        completeness = infer_semantic_completeness(case, trigger_event_id)
        if not completeness["can_auto_enrich"]:
            raise APIError(422, "NO_SUPPORTED_ENRICHMENT", "此截点没有可凭已定位证据安全追加的研究标记。")
        return self.append_event(case_id, expected_version, semantic_extension(case, completeness))

    def list_attachments(self, case_id: str, event_id: str | None = None) -> list[dict]:
        self.store.case(case_id)
        return self.media.list_for_case(case_id, event_id)

    def add_attachment(self, case_id: str, event_id: str, filename: str, raw: bytes) -> dict:
        case = ResearchCase.model_validate(self.store.case(case_id))
        if event_id not in {event.event_id for event in case.timeline}:
            raise APIError(404, "EVENT_NOT_FOUND", "该事件不属于当前病例最新版本。")
        return self.media.add(case_id, event_id, filename, raw)

    def attachment_content(self, case_id: str, attachment_id: str) -> tuple[bytes, str, str]:
        self.store.case(case_id)
        return self.media.get_content(case_id, attachment_id)

    def delete_attachment(self, case_id: str, attachment_id: str) -> dict:
        self.store.case(case_id)
        return self.media.delete(case_id, attachment_id)

    def list_annotations(self) -> list[dict]:
        return self.annotations.list_all()

    def annotation_tasks(self) -> list[dict]:
        references = self.annotations.map_all()
        tasks = []
        for case in self.store.cases():
            for event in case["timeline"]:
                scenario_id = f"{case['case_id']}:v{case['version']}:{event['event_id']}"
                tasks.append({
                    "scenario_id": scenario_id,
                    "case_id": case["case_id"],
                    "case_version": case["version"],
                    "trigger_event_id": event["event_id"],
                    "annotated": scenario_id in references,
                })
        return tasks

    def annotation_material(self, case_id: str, version: int, trigger_event_id: str) -> dict:
        case = ResearchCase.model_validate(self.store.case(case_id, version))
        return review_material(case, trigger_event_id)

    def own_annotation(self, scenario_id: str, annotator_id: str) -> dict | None:
        return self.annotations.own(scenario_id, annotator_id)

    def save_annotation(self, scenario_id: str, body: BlindAnnotationInput) -> dict:
        material = self.annotation_material(body.case_id, body.case_version, body.trigger_event_id)
        validate_reference(material, body.model_dump(mode="json"))
        return self.annotations.upsert(scenario_id, body.model_copy(update={"input_sha256": material["input_sha256"]}))

    def delete_annotation(self, scenario_id: str, annotator_id: str | None = None) -> dict:
        return self.annotations.delete(scenario_id, annotator_id)

    def review_panel_tasks(self, annotator_id: str | None = None) -> list[dict]:
        tasks = []
        for case in self.store.cases():
            for event in case["timeline"]:
                scenario_id = f"{case['case_id']}:v{case['version']}:{event['event_id']}"
                status = self.review_panel.scenario_rater_status(scenario_id, annotator_id)
                tasks.append({
                    "scenario_id": scenario_id,
                    "case_id": case["case_id"],
                    "case_version": case["version"],
                    "trigger_event_id": event["event_id"],
                    **status,
                })
        return tasks

    def review_panel_own(self, scenario_id: str, annotator_id: str) -> dict | None:
        return self.review_panel.own_submission(scenario_id, annotator_id)

    def save_review_submission(self, scenario_id: str, body: MultiRaterSubmissionInput) -> dict:
        material = self.annotation_material(body.case_id, body.case_version, body.trigger_event_id)
        validate_reference(material, body.model_dump(mode="json"))
        return self.review_panel.upsert_submission(
            scenario_id,
            body.model_copy(update={"input_sha256": material["input_sha256"]}),
        )

    def delete_review_submission(self, scenario_id: str, annotator_id: str) -> dict:
        return self.review_panel.delete_submission(scenario_id, annotator_id)

    def review_panel_agreement(self) -> dict:
        return self.review_panel.agreement_report()

    def list_adjudications(self) -> list[dict]:
        return self.review_panel.list_adjudications()

    def save_adjudication(self, scenario_id: str, body: AdjudicationInput) -> dict:
        material = self.annotation_material(body.case_id, body.case_version, body.trigger_event_id)
        validate_reference(material, body.model_dump(mode="json"))
        return self.review_panel.upsert_adjudication(
            scenario_id,
            body.model_copy(update={"input_sha256": material["input_sha256"]}),
        )

    def delete_adjudication(self, scenario_id: str) -> dict:
        return self.review_panel.delete_adjudication(scenario_id)

    def export_panel_annotations_jsonl(self) -> str:
        return self.review_panel.export_annotations_jsonl()

    def export_panel_adjudication_jsonl(self) -> str:
        return self.review_panel.export_adjudication_jsonl()

    def temporal_audit_run(self, run_id: str) -> dict:
        rep = self.report(run_id)
        original = ResearchCase.model_validate(self.store.case(rep["case_id"], rep["case_version"]))
        return audit_temporal_boundary(original, rep)

    def evaluate_experiments(self, *, case_ids: list[str] | None = None,
                             case_versions: dict[str, int] | None = None,
                             trigger_scope: str = "all",
                             reference_source: str = "merged") -> dict:
        if case_versions is not None and (case_ids is None or set(case_ids) != case_versions.keys()):
            raise APIError(422, "CASE_SELECTION_MISMATCH", "版本清单须为每个选中的病例各指定一个版本。")
        if case_ids is None:
            selected = self.store.cases()
        else:
            if not case_ids or len(set(case_ids)) != len(case_ids):
                raise APIError(422, "INVALID_CASE_SELECTION", "请选择至少一个病例，每个病例仅纳入一次。")
            selected = [self.store.case(case_id, case_versions[case_id] if case_versions else None)
                        for case_id in sorted(case_ids)]
        if not selected:
            raise APIError(422, "NO_CASES_AVAILABLE", "病例库为空，无法执行实验评测。")
        refs = (
            self.annotations.map_all()
            if reference_source == "single_only"
            else self.review_panel.resolve_gold_references(self.annotations.map_all())
        )
        return evaluate_library(
            [ResearchCase.model_validate(case) for case in selected],
            trigger_scope=trigger_scope,
            annotations=refs,
        )

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
        selected = route_case(case, request.trigger_event_id, request.routing_mode)["selected_agents"]
        generator = self.settings.make_generator(selected_agents=selected) if payload["mode"] == "llm" else None
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
                        "pending_nodes": [], "metrics": empty_metrics(), "error": None,
                        "model_configuration": generator.configuration_snapshot if generator is not None else []}
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
            report["model_configuration"] = generator.configuration_snapshot if generator is not None else []
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
        self.settings.close()
        self.imports.clear()
        self.store.close()
