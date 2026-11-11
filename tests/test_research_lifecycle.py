"""Failure-boundary checks for durable research runs and local worker limits."""

from contextlib import contextmanager
import sqlite3
from threading import Event
import time

import pytest

from mdt_demo.api_schemas import APIError
from mdt_demo.research import service as service_module
from mdt_demo.research.engine import execute
from mdt_demo.research.schemas import ResearchCase, RunRequest
from mdt_demo.research.service import ResearchService
from mdt_demo.research.store import TERMINAL


def request():
    return RunRequest(case_id="LUNG-SYN-001", case_version=1, trigger_event_id="E002")


@contextmanager
def opened_service(directory, **options):
    service = ResearchService(directory, event_delay=0, **options)
    try:
        yield service
    finally:
        service.close()


def finish(service, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = service.run(run_id)
        if snapshot["status"] in TERMINAL:
            return snapshot
        time.sleep(.005)
    pytest.fail("Research worker failed to reach a terminal state")


def test_completion_rolls_back_report_and_both_events_on_terminal_write_failure(tmp_path, monkeypatch):
    with opened_service(tmp_path) as service:
        # Pause submission so the real store can be exercised at the commit boundary.
        monkeypatch.setattr(service._pool, "submit", lambda *args, **kwargs: None)
        run_id = service.start(request())["run_id"]
        saved_request, case = service.store.run_input(run_id)
        report = execute(ResearchCase.model_validate(case), RunRequest.model_validate(saved_request),
                         run_id, lambda *args: None, lambda: False)
        before = service.run(run_id)
        before_events = service.events(run_id)

        # Fail the final audit INSERT after the report and report.generated writes.
        with sqlite3.connect(service.store.path) as db:
            db.execute("""
                CREATE TRIGGER fail_terminal_commit BEFORE INSERT ON audit_events
                WHEN json_extract(NEW.document, '$.type') = 'run.completed'
                BEGIN SELECT RAISE(ABORT, 'injected terminal write failure'); END
            """)
        with pytest.raises(sqlite3.IntegrityError, match="injected terminal write failure"):
            service.store.complete(run_id, report, service._update)

        assert service.run(run_id) == before
        assert service.events(run_id) == before_events
        with pytest.raises(APIError) as error:
            service.report(run_id)
        assert error.value.code == "REPORT_NOT_READY"
        with sqlite3.connect(service.store.path) as db:
            assert db.execute("SELECT report FROM runs WHERE run_id=?", (run_id,)).fetchone()[0] is None
            db.execute("DROP TRIGGER fail_terminal_commit")

        completed = service.store.complete(run_id, report, service._update)
        assert completed["status"] == "completed" and completed["report_ready"]
        assert completed["last_seq"] == before["last_seq"] + 2
        assert [event["type"] for event in service.events(run_id)[-2:]] == [
            "report.generated", "run.completed",
        ]
        assert service.report(run_id) == report


def test_timeout_never_saves_a_success_report(tmp_path, monkeypatch):
    # A deterministic fake clock crosses the deadline at the first cancellation
    # check; no real waiting or external provider is required.
    clock_values = iter([0.0, 1.0, 1.0])
    monkeypatch.setattr(service_module, "time", type("Clock", (), {
        "monotonic": staticmethod(lambda: next(clock_values, 1.0)),
    }))
    with opened_service(tmp_path, run_timeout_seconds=.1) as service:
        run_id = service.start(request())["run_id"]
        snapshot = finish(service, run_id)
        assert snapshot["status"] == "failed"
        assert snapshot["error"] == "run_timeout"
        assert snapshot["report_ready"] is False
        assert snapshot["metrics"]["agent_calls"] == 0
        assert service.events(run_id)[-1]["type"] == "run.failed"
        assert not any(event["type"] in {"report.generated", "run.completed"}
                       for event in service.events(run_id))
        with pytest.raises(APIError) as error:
            service.report(run_id)
        assert error.value.code == "REPORT_NOT_READY"


@pytest.mark.parametrize("interrupted_status", ["queued", "running", "cancel_requested"])
def test_restart_marks_unfinished_run_failed_once_and_preserves_input(tmp_path, monkeypatch, interrupted_status):
    with opened_service(tmp_path) as service:
        # Reproduce persisted work abandoned by a process before its worker exits.
        monkeypatch.setattr(service._pool, "submit", lambda *args, **kwargs: None)
        run_id = service.start(request())["run_id"]
        if interrupted_status != "queued":
            service._emit(run_id, "run.started", "INITIALIZING", {})
            service._emit(run_id, "agent.started", "ANALYZING", {}, "oncology")
        if interrupted_status == "cancel_requested":
            service.cancel(run_id)
        assert service.run(run_id)["status"] == interrupted_status
        frozen_input = service.store.run_input(run_id)
        original_events = service.events(run_id)

    with opened_service(tmp_path) as restarted:
        snapshot = restarted.run(run_id)
        events = restarted.events(run_id)
        assert snapshot["status"] == "failed"
        assert snapshot["error"] == "process_interrupted"
        assert snapshot["report_ready"] is False
        assert snapshot["running_nodes"] == []
        assert restarted.store.run_input(run_id) == frozen_input
        assert events[:-1] == original_events
        assert events[-1]["seq"] == len(original_events) + 1
        assert events[-1]["type"] == "run.failed"
        assert events[-1]["payload"]["error_code"] == "process_interrupted"
        if interrupted_status != "queued":
            oncology = next(agent for agent in snapshot["agents"] if agent["agent_id"] == "oncology")
            assert oncology["status"] == "failed"
        with pytest.raises(APIError) as error:
            restarted.report(run_id)
        assert error.value.code == "REPORT_NOT_READY"

    with opened_service(tmp_path) as restarted_again:
        assert restarted_again.events(run_id) == events
        assert restarted_again.run(run_id) == snapshot


def test_four_unfinished_runs_reject_fifth_without_creating_a_record(tmp_path, monkeypatch):
    release = Event()
    entered = Event()
    real_execute = service_module.execute

    def paused_execute(*args, **kwargs):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("Test did not release research workers")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(service_module, "execute", paused_execute)
    with opened_service(tmp_path) as service:
        try:
            ids = [service.start(request())["run_id"] for _ in range(4)]
            assert entered.wait(1)
            assert len(service.store.runs(active_only=True)) == 4
            with pytest.raises(APIError) as error:
                service.start(request())
            assert error.value.status_code == 429
            assert error.value.code == "RUN_LIMIT"
            assert {run["run_id"] for run in service.runs()} == set(ids)
            for run_id in ids:
                service.cancel(run_id)
        finally:
            release.set()

        for run_id in ids:
            snapshot = finish(service, run_id)
            assert snapshot["status"] == "cancelled"
            assert snapshot["report_ready"] is False

        # Completed/cancelled runs release capacity for subsequent work.
        replacement = service.start(request())["run_id"]
        assert finish(service, replacement)["status"] == "completed"
