"""SQLite persistence for immutable case revisions and durable run events.

Each append and its resulting snapshot are committed together. Browser replay reads
the committed database, so a process restart cannot invent or lose emitted events.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Callable

from ..api_schemas import APIError
from .schemas import case_with_synthetic_event

TERMINAL = {"completed", "incomplete", "failed", "cancelled"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class ResearchStore:
    backend = "sqlite"

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT NOT NULL, version INTEGER NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY (case_id, version)
            );
            CREATE TABLE IF NOT EXISTS clinical_events (
                case_id TEXT NOT NULL, event_id TEXT NOT NULL,
                introduced_in_version INTEGER NOT NULL, document TEXT NOT NULL,
                PRIMARY KEY (case_id, event_id)
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                status TEXT NOT NULL, snapshot TEXT NOT NULL,
                request TEXT NOT NULL, frozen_case TEXT NOT NULL, report TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                run_id TEXT NOT NULL REFERENCES runs(run_id), seq INTEGER NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY (run_id, seq)
            );
            CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at DESC);
            CREATE TABLE IF NOT EXISTS import_batches (
                batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, document TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS model_settings (
                key TEXT PRIMARY KEY, document TEXT NOT NULL
            );
        """)
        for table in ("cases", "clinical_events", "audit_events", "import_batches"):
            for operation in ("UPDATE", "DELETE"):
                self._db.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation.lower()}
                    BEFORE {operation} ON {table}
                    BEGIN SELECT RAISE(ABORT, 'append-only research records'); END
                """)
        self._db.commit()

    def seed(self, cases: list[dict]) -> None:
        with self._lock, self._db:
            for case in cases:
                if self._db.execute("SELECT 1 FROM cases WHERE case_id=?", (case["case_id"],)).fetchone():
                    continue
                self._db.execute("INSERT INTO cases VALUES(?,?,?)", (case["case_id"], case["version"], dumps(case)))
                for event in case["timeline"]:
                    self._db.execute("INSERT INTO clinical_events VALUES(?,?,?,?)", (
                        case["case_id"], event["event_id"], event["introduced_in_version"], dumps(event),
                    ))

    def cases(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("""
                SELECT c.document FROM cases c
                INNER JOIN (SELECT case_id, MAX(version) version FROM cases GROUP BY case_id) latest
                ON c.case_id=latest.case_id AND c.version=latest.version ORDER BY c.case_id
            """).fetchall()
            return [json.loads(row[0]) for row in rows]

    def import_history(self) -> list[dict]:
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute(
                "SELECT document FROM import_batches ORDER BY created_at DESC LIMIT 50").fetchall()]

    def import_cases(self, cases: list[dict], summary: dict) -> dict:
        """Validate upstream; preserve every existing version and commit one batch."""
        with self._lock, self._db:
            old = self._db.execute("SELECT document FROM import_batches WHERE batch_id=?", (summary["batch_id"],)).fetchone()
            if old:
                return {**json.loads(old[0]), "already_imported": True}
            inserted, skipped = [], []
            for case in cases:
                old = self._db.execute("SELECT document FROM cases WHERE case_id=? AND version=1", (case["case_id"],)).fetchone()
                if old:
                    if json.loads(old[0]) != case:
                        raise APIError(409, "IMPORT_CASE_CONFLICT", "同一来源病例已有不同内容；本批次未写入，请检查数据版本。")
                    skipped.append(case["case_id"])
                    continue
                self._db.execute("INSERT INTO cases VALUES(?,?,?)", (case["case_id"], 1, dumps(case)))
                for event in case["timeline"]:
                    self._db.execute("INSERT INTO clinical_events VALUES(?,?,?,?)", (case["case_id"], event["event_id"], 1, dumps(event)))
                inserted.append(case["case_id"])
            result = {**deepcopy(summary), "created_at": utcnow(), "imported_case_ids": inserted,
                      "skipped_case_ids": skipped, "already_imported": False}
            self._db.execute("INSERT INTO import_batches VALUES(?,?,?)", (summary["batch_id"], result["created_at"], dumps(result)))
            return result

    def case(self, case_id: str, version: int | None = None) -> dict:
        with self._lock:
            if version is None:
                row = self._db.execute("SELECT document FROM cases WHERE case_id=? ORDER BY version DESC LIMIT 1", (case_id,)).fetchone()
            else:
                row = self._db.execute("SELECT document FROM cases WHERE case_id=? AND version=?", (case_id, version)).fetchone()
            if row is None:
                raise APIError(404, "CASE_NOT_FOUND", "未找到该研究病例或病例版本。")
            return json.loads(row[0])

    def append_event(self, case_id: str, expected_version: int, event: dict, validate: Callable[[dict], dict]) -> dict:
        with self._lock, self._db:
            case = self.case(case_id)
            if case["version"] != expected_version:
                raise APIError(409, "CASE_VERSION_CONFLICT", "病例已更新，请刷新后重新提交事件。")
            case, created = case_with_synthetic_event(case, event)
            new_version = case["version"]
            case = validate(case)
            self._db.execute("INSERT INTO clinical_events VALUES(?,?,?,?)", (
                case_id, created["event_id"], new_version, dumps(created),
            ))
            self._db.execute("INSERT INTO cases VALUES(?,?,?)", (case_id, new_version, dumps(case)))
            return case

    def create_run(self, snapshot: dict, request: dict, frozen_case: dict) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,NULL)", (
                snapshot["run_id"], snapshot["created_at"], snapshot["status"],
                dumps(snapshot), dumps(request), dumps(frozen_case),
            ))

    def run(self, run_id: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT snapshot FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise APIError(404, "RUN_NOT_FOUND", "未找到该研究运行。")
            return json.loads(row[0])

    def run_input(self, run_id: str) -> tuple[dict, dict]:
        with self._lock:
            row = self._db.execute("SELECT request,frozen_case FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise APIError(404, "RUN_NOT_FOUND", "未找到该研究运行。")
            return json.loads(row[0]), json.loads(row[1])

    def runs(self, limit: int = 100, *, active_only: bool = False) -> list[dict]:
        with self._lock:
            if active_only:
                rows = self._db.execute("SELECT snapshot FROM runs WHERE status NOT IN ('completed','incomplete','failed','cancelled') ORDER BY created_at DESC").fetchall()
            else:
                rows = self._db.execute("SELECT snapshot FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def append_audit(self, run_id: str, event_type: str, stage: str, payload: dict,
                     agent_id: str | None, update: Callable[[dict, dict], None]) -> tuple[dict, dict]:
        with self._lock, self._db:
            return self._append_audit(run_id, event_type, stage, payload, agent_id, update)

    def _append_audit(self, run_id, event_type, stage, payload, agent_id, update):
        """Caller owns the lock and transaction, including multi-event completion."""
        snapshot = self.run(run_id)
        seq = snapshot["last_seq"] + 1
        event = {"event_id": f"evt_{seq:06d}", "run_id": run_id, "seq": seq,
                 "timestamp": utcnow(), "type": event_type, "stage": stage,
                 "agent_id": agent_id, "payload": deepcopy(payload)}
        update(snapshot, event)
        snapshot["last_seq"] = seq
        snapshot["updated_at"] = event["timestamp"]
        self._db.execute("INSERT INTO audit_events VALUES(?,?,?)", (run_id, seq, dumps(event)))
        self._db.execute("UPDATE runs SET status=?,snapshot=? WHERE run_id=?", (
            snapshot["status"], dumps(snapshot), run_id,
        ))
        return event, snapshot

    def events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> list[dict]:
        with self._lock:
            self.run(run_id)
            return [json.loads(row[0]) for row in self._db.execute(
                "SELECT document FROM audit_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, after_seq, limit),
            ).fetchall()]

    def complete(self, run_id: str, report: dict, update: Callable[[dict, dict], None]) -> dict:
        """Report availability and its audit event become visible in one transaction."""
        with self._lock, self._db:
            snapshot = self.run(run_id)
            if snapshot["status"] in TERMINAL or snapshot["cancel_requested"]:
                raise APIError(409, "RUN_NOT_ACTIVE", "运行已经停止，不能保存成功报告。")
            self._db.execute("UPDATE runs SET report=? WHERE run_id=?", (dumps(report), run_id))
            self._append_audit(run_id, "report.generated", "REPORTING", {
                "status": report["status"], "final_decision": report["final_decision"],
                "metrics": report["metrics"],
            }, None, update)
            _, snapshot = self._append_audit(run_id, "run.completed", "COMPLETED", {
                "status": report["status"],
            }, None, update)
            return snapshot

    def report(self, run_id: str) -> dict:
        with self._lock:
            snapshot = self.run(run_id)
            if not snapshot["report_ready"]:
                raise APIError(409, "REPORT_NOT_READY", "报告尚未保存，已取消运行不生成报告。")
            row = self._db.execute("SELECT report FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row[0]:
                raise APIError(500, "REPORT_UNREADABLE", "已保存报告无法读取。")
            return json.loads(row[0])

    def health(self) -> dict:
        with self._lock:
            self._db.execute("SELECT 1")
        return {"backend": self.backend, "database": self.path.name, "connected": True,
                "transactions": True, "schema_version": 1}

    def load_model_settings(self) -> dict:
        with self._lock:
            return {row["key"]: json.loads(row["document"]) for row in self._db.execute("SELECT * FROM model_settings")}

    def save_model_setting(self, key: str, value: dict) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO model_settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET document=excluded.document",
                             (key, dumps(value)))

    def delete_model_setting(self, key: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM model_settings WHERE key=?", (key,))

    def close(self) -> None:
        with self._lock:
            self._db.close()
