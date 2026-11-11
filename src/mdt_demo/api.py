"""FastAPI adapter and same-origin static frontend. Run with one local worker."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api_schemas import APIError, CreateRun, RunOptions
from .runtime import RunManager, TERMINAL
from .research.service import ResearchService
from .research.api import router as research_router
from .research.provider_api import router as provider_router, provider_error
from .research.provider import ProviderError
from .research.import_api import router as import_router

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_ORIGINS = {
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8000", "http://127.0.0.1:8000", "http://testserver",
}


def create_app(output_dir: Path | None = None, *, event_delay: float | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        delay = float(os.getenv("MDT_DEMO_EVENT_DELAY", "0.22")) if event_delay is None else event_delay
        app.state.manager = RunManager(output_dir or PROJECT_ROOT / "outputs", event_delay=delay)
        app.state.research = ResearchService(output_dir or PROJECT_ROOT / "outputs", event_delay=delay)
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.manager.close)
            await asyncio.to_thread(app.state.research.close)

    app = FastAPI(title="MDT Lab · 事件驱动科研 API", version="0.3.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.add_middleware(CORSMiddleware, allow_origins=sorted(ALLOWED_ORIGINS),
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "Last-Event-ID"])
    app.include_router(research_router)
    app.include_router(provider_router)
    app.include_router(import_router)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = f"req_{uuid4().hex}"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("origin") not in ALLOWED_ORIGINS | {None}:
            return error_response(request, APIError(403, "ORIGIN_NOT_ALLOWED", "不允许此来源发起本地运行。"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def success(request: Request, data, status_code: int = 200):
        from fastapi.encoders import jsonable_encoder
        return JSONResponse(status_code=status_code, content=jsonable_encoder({
            "data": data, "request_id": request.state.request_id,
            "timestamp": datetime.now(timezone.utc),
        }))

    def error_response(request: Request, exc: APIError):
        return JSONResponse(status_code=exc.status_code, content={
            "error": {"code": exc.code, "message": exc.message,
                      "details": exc.details, "retryable": exc.status_code in {429, 503}},
            "request_id": getattr(request.state, "request_id", "unknown"),
        })

    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError):
        return error_response(request, exc)

    @app.exception_handler(ProviderError)
    async def handle_provider_error(request: Request, exc: ProviderError):
        return provider_error(exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(map(str, error["loc"])), "message": error["msg"]}
                   for error in exc.errors()]
        return error_response(request, APIError(422, "VALIDATION_ERROR", "请求参数校验失败。", details))

    @app.get("/api/v1/health")
    def health(request: Request):
        return success(request, {"status": "ok", "version": "0.2.0", "mode": "mock",
                                 "event_delay": request.app.state.manager.event_delay})

    @app.get("/api/v1/cases")
    def cases(request: Request):
        return success(request, [
            {**case.model_dump(mode="json"), "title": "影像资料完整性评议", "event_count": len(case.timeline)}
            for case in request.app.state.manager.cases.values()
        ])

    @app.get("/api/v1/cases/{case_id}")
    def case_detail(case_id: str, request: Request):
        return success(request, request.app.state.manager.get_case(case_id))

    @app.get("/api/v1/llm/status")
    def llm_status(request: Request):
        return success(request, {"enabled": False, "credentials_configured": False,
                                 "message": "真实模型适配器尚未实现；当前为完全离线的预设 Mock。"})

    @app.post("/api/v1/runs", status_code=202)
    def start_run(body: CreateRun, request: Request):
        return success(request, request.app.state.manager.start(body), 202)

    @app.get("/api/v1/runs")
    def list_runs(request: Request):
        return success(request, request.app.state.manager.list_runs())

    @app.get("/api/v1/runs/{run_id}")
    def run_detail(run_id: str, request: Request):
        return success(request, request.app.state.manager.get(run_id))

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(run_id: str, request: Request):
        return success(request, request.app.state.manager.cancel(run_id))

    @app.post("/api/v1/runs/{run_id}/rerun", status_code=202)
    def rerun(run_id: str, request: Request):
        manager = request.app.state.manager
        old = manager.get(run_id)
        body = CreateRun(case_id=old.case_id, mode="mock", options=RunOptions(scenario=old.scenario))
        return success(request, manager.start(body, source_run_id=run_id), 202)

    @app.get("/api/v1/runs/{run_id}/audit")
    def audit(run_id: str, request: Request, after_seq: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500)):
        events = request.app.state.manager.events(run_id, after_seq, limit)
        return success(request, {"events": events, "next_seq": events[-1].seq if events else after_seq})

    @app.get("/api/v1/runs/{run_id}/audit/download")
    def download_audit(run_id: str, request: Request):
        manager = request.app.state.manager
        snapshot = manager.get(run_id)
        path = manager.output_dir / snapshot.run_id / "audit.jsonl"
        if not path.exists():
            raise APIError(409, "AUDIT_NOT_READY", "运行尚未开始，请稍后重试。")
        return FileResponse(path, filename=f"{run_id}_audit.jsonl", media_type="application/x-ndjson")

    @app.get("/api/v1/runs/{run_id}/report")
    def report(run_id: str, request: Request):
        return success(request, request.app.state.manager.report(run_id))

    @app.get("/api/v1/runs/{run_id}/report/download")
    def download_report(run_id: str, request: Request):
        manager = request.app.state.manager
        manager.report(run_id)
        return FileResponse(manager.output_dir / run_id / "report.json", filename=f"{run_id}_report.json",
                            media_type="application/json")

    @app.websocket("/api/v1/runs/{run_id}/events")
    async def run_events(websocket: WebSocket, run_id: str, after_seq: int = Query(0, ge=0)):
        if websocket.headers.get("origin") not in ALLOWED_ORIGINS | {None}:
            await websocket.close(code=4403)
            return
        manager = websocket.app.state.manager
        try:
            manager.get(run_id)
        except APIError:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        cursor = after_seq
        idle_ticks = 0
        try:
            while True:
                events = manager.events(run_id, cursor)
                for item in events:
                    await websocket.send_json(item.model_dump(mode="json"))
                    cursor = item.seq
                snapshot = manager.get(run_id)
                if snapshot.status in TERMINAL and cursor >= snapshot.last_seq:
                    await websocket.close(code=1000)
                    return
                idle_ticks += 1
                if idle_ticks >= 100:
                    await websocket.send_json({"type": "heartbeat"})
                    idle_ticks = 0
                await asyncio.sleep(0.1)
        except (WebSocketDisconnect, RuntimeError):
            return

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str, request: Request):
        if path.startswith("api/"):
            raise APIError(404, "ENDPOINT_NOT_FOUND", "接口不存在。")
        root = (PROJECT_ROOT / "frontend" / "dist").resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise APIError(404, "NOT_FOUND", "资源不存在。")
        if target.is_file():
            return FileResponse(target)
        if Path(path).suffix:
            raise APIError(404, "NOT_FOUND", "资源不存在。")
        if (root / "index.html").exists():
            return FileResponse(root / "index.html")
        return JSONResponse(status_code=503, content={"error": {
            "code": "FRONTEND_NOT_BUILT", "message": "请先在 frontend 目录执行 npm run build。",
        }})

    return app


app = create_app()
