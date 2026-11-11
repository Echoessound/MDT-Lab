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
from .schemas import RunRequest
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


@router.get("/health")
def health(request: Request):
    return {"data": {"status": "ok", "version": "0.3.0", "storage": "sqlite", "stream": "sse",
                     "event_delay": request.app.state.research.event_delay}}


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
            version: int | None = Query(None, ge=1), routing_mode: Literal["event", "fixed"] = "event"):
    return {"data": request.app.state.research.routing(case_id, trigger_event_id, version, routing_mode)}


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
