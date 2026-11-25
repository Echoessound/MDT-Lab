"""Versioned research API with durable, replayable server-sent events."""

import asyncio
from datetime import date
import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator

from ..api_schemas import APIError
from .adjudication import AdjudicationInput, MultiRaterSubmissionInput
from .evaluation import BlindAnnotationInput
from .media_store import MAX_ATTACHMENT_BYTES
from .schemas import Identifier, RunRequest
from .store import TERMINAL

router = APIRouter(prefix="/api/v2", tags=["纵向 MDT 研究"])


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    occurred_at: date
    event_type: Literal["diagnosis", "imaging", "pathology", "molecular_test", "procedure", "treatment",
                        "medication", "toxicity", "follow_up", "progression", "recurrence", "observation"]
    title: str = Field(min_length=1, max_length=200)
    facts: dict[Annotated[str, Field(min_length=1, max_length=80)],
                Annotated[StrictStr, Field(max_length=1000)] | StrictInt | StrictFloat | StrictBool | None] = Field(min_length=1, max_length=50)

    @field_validator("occurred_at", mode="before")
    @classmethod
    def date_only(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("日期必须为 YYYY-MM-DD")
        return value


class AppendEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)
    event: EventInput


class AutoEnrichInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)
    trigger_event_id: str | None = Field(default=None, min_length=1, max_length=80)


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_ids: list[Identifier] | None = Field(default=None, max_length=50)
    case_versions: dict[Identifier, Annotated[int, Field(ge=1, strict=True)]] | None = Field(default=None, max_length=50)
    trigger_scope: Literal["all", "latest"] = "all"
    reference_source: Literal["merged", "single_only"] = "merged"


@router.get("/health")
def health(request: Request):
    return {"data": {"status": "ok", "version": "0.3.0", "storage": request.app.state.research.store.health()["backend"], "stream": "sse",
                     "event_delay": request.app.state.research.event_delay}}


@router.get("/storage")
def storage(request: Request):
    return {"data": {**request.app.state.research.store.health(), "status": "connected"}}


@router.get("/cases")
def cases(request: Request):
    return {"data": request.app.state.research.cases()}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, request: Request, version: int | None = Query(None, ge=1)):
    return {"data": request.app.state.research.case(case_id, version)}


@router.post("/cases/{case_id}/events", status_code=201)
def append_event(case_id: str, body: AppendEvent, request: Request):
    return {"data": request.app.state.research.append_event(case_id, body.expected_version, body.event.model_dump(mode="json"))}


@router.get("/cases/{case_id}/routing")
def routing(case_id: str, request: Request, trigger_event_id: str = Query(min_length=1),
            version: int | None = Query(None, ge=1), routing_mode: Literal["event", "fixed", "adaptive"] = "event"):
    return {"data": request.app.state.research.routing(case_id, trigger_event_id, version, routing_mode)}


@router.get("/cases/{case_id}/longitudinal-dynamics")
def longitudinal_dynamics(case_id: str, request: Request, version: int | None = Query(None, ge=1)):
    return {"data": request.app.state.research.longitudinal_dynamics(case_id, version)}


@router.get("/cases/{case_id}/workflow-plan")
def workflow_plan(case_id: str, request: Request, trigger_event_id: str | None = Query(None, min_length=1),
                  version: int | None = Query(None, ge=1)):
    return {"data": request.app.state.research.workflow_plan(case_id, trigger_event_id, version)}


@router.get("/cases/{case_id}/imaging")
def imaging_pipeline(case_id: str, request: Request, trigger_event_id: str | None = Query(None, min_length=1),
                     version: int | None = Query(None, ge=1)):
    return {"data": request.app.state.research.imaging_pipeline(case_id, trigger_event_id, version)}


@router.get("/cases/{case_id}/ablation")
def ablation_matrix(case_id: str, request: Request, trigger_event_id: str | None = Query(None, min_length=1),
                    version: int | None = Query(None, ge=1)):
    return {"data": request.app.state.research.ablation_matrix(case_id, trigger_event_id, version)}


@router.post("/cases/{case_id}/auto-enrich", status_code=201)
def auto_enrich(case_id: str, body: AutoEnrichInput, request: Request):
    return {"data": request.app.state.research.auto_enrich_case(case_id, body.expected_version, body.trigger_event_id)}


@router.get("/cases/{case_id}/attachments")
def list_attachments(case_id: str, request: Request, event_id: str | None = Query(None, min_length=1)):
    return {"data": request.app.state.research.list_attachments(case_id, event_id)}


@router.post("/cases/{case_id}/events/{event_id}/attachments", status_code=201)
async def upload_attachment(case_id: str, event_id: str, request: Request, filename: str = Query(min_length=1, max_length=160)):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise APIError(413, "ATTACHMENT_SIZE_LIMIT", "附件超过 10MB 大小限制。")
    record = await asyncio.to_thread(
        request.app.state.research.add_attachment, case_id, event_id, filename, bytes(raw)
    )
    return {"data": record}


@router.get("/cases/{case_id}/attachments/{attachment_id}/content")
def get_attachment_content(case_id: str, attachment_id: str, request: Request):
    raw, mime_type, filename = request.app.state.research.attachment_content(case_id, attachment_id)
    disposition = "inline" if mime_type.startswith("image/") else f'attachment; filename="{filename}"'
    return Response(
        raw,
        media_type=mime_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/cases/{case_id}/attachments/{attachment_id}")
def delete_attachment(case_id: str, attachment_id: str, request: Request):
    return {"data": request.app.state.research.delete_attachment(case_id, attachment_id)}


@router.post("/experiments/evaluate")
def evaluate_experiments(body: EvaluateRequest, request: Request):
    return {"data": request.app.state.research.evaluate_experiments(
        case_ids=body.case_ids, case_versions=body.case_versions,
        trigger_scope=body.trigger_scope, reference_source=body.reference_source,
    )}


@router.get("/annotations")
def list_annotations(request: Request):
    return {"data": request.app.state.research.list_annotations()}


@router.get("/annotations/tasks")
def annotation_tasks(request: Request):
    return {"data": request.app.state.research.annotation_tasks()}


@router.get("/annotations/material")
def annotation_material(request: Request, case_id: str = Query(min_length=1, max_length=80),
                        version: int = Query(ge=1), trigger_event_id: str = Query(min_length=1, max_length=80)):
    return {"data": request.app.state.research.annotation_material(case_id, version, trigger_event_id)}


@router.get("/annotations/own")
def own_annotation(request: Request, scenario_id: str = Query(min_length=1),
                   annotator_id: str = Query(min_length=1, max_length=80)):
    return {"data": request.app.state.research.own_annotation(scenario_id, annotator_id)}


@router.put("/annotations/{scenario_id:path}")
def save_annotation(scenario_id: str, body: BlindAnnotationInput, request: Request):
    return {"data": request.app.state.research.save_annotation(scenario_id, body)}


@router.delete("/annotations/{scenario_id:path}")
def delete_annotation(scenario_id: str, request: Request,
                      annotator_id: str | None = Query(default=None, min_length=1, max_length=80)):
    return {"data": request.app.state.research.delete_annotation(scenario_id, annotator_id)}


@router.get("/review-panel/tasks")
def review_panel_tasks(request: Request, annotator_id: str | None = Query(default=None, min_length=1, max_length=80)):
    return {"data": request.app.state.research.review_panel_tasks(annotator_id)}


@router.get("/review-panel/own")
def review_panel_own(request: Request, scenario_id: str = Query(min_length=1),
                     annotator_id: str = Query(min_length=1, max_length=80)):
    return {"data": request.app.state.research.review_panel_own(scenario_id, annotator_id)}


@router.put("/review-panel/submissions/{scenario_id:path}")
def save_review_submission(scenario_id: str, body: MultiRaterSubmissionInput, request: Request):
    return {"data": request.app.state.research.save_review_submission(scenario_id, body)}


@router.delete("/review-panel/submissions/{scenario_id:path}")
def delete_review_submission(scenario_id: str, request: Request,
                             annotator_id: str = Query(min_length=1, max_length=80)):
    return {"data": request.app.state.research.delete_review_submission(scenario_id, annotator_id)}


@router.get("/review-panel/agreement")
def review_panel_agreement(request: Request):
    return {"data": request.app.state.research.review_panel_agreement()}


@router.get("/review-panel/adjudications")
def list_adjudications(request: Request):
    return {"data": request.app.state.research.list_adjudications()}


@router.put("/review-panel/adjudications/{scenario_id:path}")
def save_adjudication(scenario_id: str, body: AdjudicationInput, request: Request):
    return {"data": request.app.state.research.save_adjudication(scenario_id, body)}


@router.delete("/review-panel/adjudications/{scenario_id:path}")
def delete_adjudication(scenario_id: str, request: Request):
    return {"data": request.app.state.research.delete_adjudication(scenario_id)}


@router.get("/review-panel/export/annotations.jsonl")
def export_panel_annotations(request: Request):
    content = request.app.state.research.export_panel_annotations_jsonl()
    return Response(content, media_type="application/x-ndjson",
                    headers={"Content-Disposition": 'attachment; filename="annotations.jsonl"'})


@router.get("/review-panel/export/adjudication.jsonl")
def export_panel_adjudications(request: Request):
    content = request.app.state.research.export_panel_adjudication_jsonl()
    return Response(content, media_type="application/x-ndjson",
                    headers={"Content-Disposition": 'attachment; filename="adjudication.jsonl"'})


@router.post("/runs", status_code=202)
def create_run(body: RunRequest, request: Request):
    return {"data": request.app.state.research.start(body)}


@router.get("/runs")
def runs(request: Request):
    return {"data": request.app.state.research.runs()}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, request: Request):
    return {"data": request.app.state.research.run(run_id)}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, request: Request):
    return {"data": request.app.state.research.cancel(run_id)}


@router.post("/runs/{run_id}/rerun", status_code=202)
def rerun(run_id: str, request: Request):
    return {"data": request.app.state.research.rerun(run_id)}


@router.get("/runs/{run_id}/report")
def report(run_id: str, request: Request):
    return {"data": request.app.state.research.report(run_id)}


@router.get("/runs/{run_id}/temporal-audit")
def temporal_audit(run_id: str, request: Request):
    return {"data": request.app.state.research.temporal_audit_run(run_id)}


@router.get("/runs/{run_id}/consensus-metrics")
def consensus_metrics(run_id: str, request: Request):
    return {"data": request.app.state.research.consensus_metrics_run(run_id)}


@router.get("/runs/{run_id}/report/download")
def download_report(run_id: str, request: Request):
    report = request.app.state.research.report(run_id)
    return Response(json.dumps(report, ensure_ascii=False, indent=2) + "\n", media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{report["run_id"]}_report.json"'})


@router.get("/runs/{run_id}/audit")
def audit(run_id: str, request: Request, after_seq: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500)):
    events = request.app.state.research.events(run_id, after_seq, limit)
    return {"data": {"events": events, "next_seq": events[-1]["seq"] if events else after_seq}}


@router.get("/runs/{run_id}/audit/download")
def download_audit(run_id: str, request: Request):
    service = request.app.state.research
    snapshot = service.run(run_id)
    events, cursor = [], 0
    # A stable download stops at the snapshot's committed end, even for a live run.
    while cursor < snapshot["last_seq"]:
        batch = service.events(run_id, cursor, 500)
        batch = [event for event in batch if event["seq"] <= snapshot["last_seq"]]
        if not batch:
            break
        events.extend(batch)
        cursor = batch[-1]["seq"]
    content = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
    return Response(content, media_type="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="{snapshot["run_id"]}_audit.jsonl"'})


@router.get("/runs/{run_id}/events")
async def event_stream(run_id: str, request: Request, after_seq: int = Query(0, ge=0)):
    service = request.app.state.research
    service.run(run_id)
    raw_cursor = request.headers.get("last-event-id")
    if raw_cursor is not None:
        try:
            last_event_id = int(raw_cursor)
            if last_event_id < 0:
                raise ValueError
            after_seq = max(after_seq, last_event_id)
        except ValueError:
            raise APIError(422, "INVALID_EVENT_CURSOR", "Last-Event-ID 必须是非负整数。") from None

    async def stream():
        cursor, idle_ticks = after_seq, 0
        yield ": connected\n\n"
        while not await request.is_disconnected():
            batch = service.events(run_id, cursor, 500)
            for event in batch:
                cursor = event["seq"]
                yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            snapshot = service.run(run_id)
            if snapshot["status"] in TERMINAL and cursor >= snapshot["last_seq"]:
                return
            idle_ticks = 0 if batch else idle_ticks + 1
            if idle_ticks >= 100:
                yield ": keep-alive\n\n"
                idle_ticks = 0
            await asyncio.sleep(0.1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
    })
