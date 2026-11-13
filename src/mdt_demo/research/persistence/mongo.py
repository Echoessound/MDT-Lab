"""MongoDB repository with transactionally consistent versions, runs and audits.

A replica set (including a one-member local set) or mongos is required. MongoDB
credentials belong in the URI supplied by the server, never in returned health
or error payloads. Application records are append-only through this interface;
this does not prevent a database administrator from editing collections.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import re
from typing import Callable
from uuid import uuid4

from bson import BSON
from bson.errors import InvalidDocument
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DocumentTooLarge, DuplicateKeyError, PyMongoError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from ...api_schemas import APIError

TERMINAL = {"completed", "incomplete", "failed", "cancelled"}
# Leave headroom below MongoDB's 16 MiB BSON limit for server/driver metadata.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
COLLECTIONS = (
    "case_heads", "cases", "clinical_events", "runs", "audit_events",
    "reports", "import_batches", "model_settings",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def checked(document: dict) -> dict:
    """Validate actual BSON size before a write, without leaking field contents."""
    try:
        size = len(BSON.encode(document))
    except (InvalidDocument, OverflowError, ValueError):
        raise APIError(422, "STORAGE_INVALID_DOCUMENT", "记录包含数据库不支持的字段或数值。") from None
    if size > MAX_DOCUMENT_BYTES:
        raise APIError(413, "STORAGE_DOCUMENT_TOO_LARGE", "单条研究记录超过15MB存储限制，请缩小病例窗口或批次。")
    return document


def storage_errors(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except DuplicateKeyError:
            raise APIError(409, "STORAGE_WRITE_CONFLICT", "记录已存在或并发版本冲突，请刷新后重试。") from None
        except DocumentTooLarge:
            raise APIError(413, "STORAGE_DOCUMENT_TOO_LARGE", "研究记录超过数据库单文档限制。") from None
        except PyMongoError:
            # Driver messages can contain hostnames, URI credentials or documents.
            raise APIError(503, "STORAGE_UNAVAILABLE", "MongoDB 读写失败，请检查数据库连接与副本集状态后重试。") from None
    return guarded


class MongoResearchStore:
    backend = "mongodb"

    def __init__(self, uri: str, database: str = "mdt_lab", *, client=None, timeout_ms: int = 5000):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database):
            raise APIError(422, "STORAGE_INVALID_DATABASE", "数据库名称只允许字母、数字、下划线和短横线。")
        self._owns_client = client is None
        self._client = client
        try:
            if self._client is None:
                self._client = MongoClient(
                    uri, serverSelectionTimeoutMS=timeout_ms, connectTimeoutMS=timeout_ms,
                    socketTimeoutMS=15000, retryWrites=True, appname="mdt-lab",
                )
            self.database = self._client.get_database(database, write_concern=WriteConcern("majority"))
            hello = self._client.admin.command("hello")
            if not (hello.get("setName") or hello.get("msg") == "isdbgrid") or hello.get("logicalSessionTimeoutMinutes") is None:
                raise APIError(503, "MONGODB_TRANSACTIONS_REQUIRED", "MongoDB 必须启用副本集或分片事务；请使用项目提供的单节点副本集启动方式。")
            self._ensure_indexes()
        except APIError:
            if self._owns_client and self._client is not None:
                self._client.close()
            raise
        except PyMongoError:
            if self._owns_client and self._client is not None:
                self._client.close()
            raise APIError(503, "MONGODB_CONNECTION_FAILED", "无法连接 MongoDB，请检查服务、数据库凭据及副本集配置。") from None

    def _ensure_indexes(self):
        db = self.database
        # Create all namespaces outside transactions, including empty collections.
        existing = set(db.list_collection_names())
        for name in COLLECTIONS:
            if name not in existing:
                try:
                    db.create_collection(name)
                except PyMongoError as exc:
                    # Another process may have created the namespace concurrently.
                    if getattr(exc, "code", None) != 48:
                        raise
        db.cases.create_index([("case_id", ASCENDING), ("version", DESCENDING)], unique=True)
        db.clinical_events.create_index([("case_id", ASCENDING), ("event_id", ASCENDING)], unique=True)
        db.runs.create_index([("created_at", DESCENDING)])
        db.runs.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
        db.audit_events.create_index([("run_id", ASCENDING), ("seq", ASCENDING)], unique=True)
        db.import_batches.create_index([("created_at", DESCENDING)])

    def _transaction(self, callback):
        with self._client.start_session() as session:
            return session.with_transaction(
                callback, read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"), max_commit_time_ms=10000,
            )

    @storage_errors
    def health(self) -> dict:
        self._client.admin.command("ping")
        return {"backend": self.backend, "database": self.database.name, "connected": True,
                "transactions": True, "schema_version": 1}

    @staticmethod
    def _case_document(case: dict) -> dict:
        return checked({"_id": f"{case['case_id']}:{case['version']}", "case_id": case["case_id"],
                        "version": case["version"], "document": deepcopy(case)})

    @staticmethod
    def _event_document(case_id: str, event: dict) -> dict:
        return checked({"_id": f"{case_id}:{event['event_id']}", "case_id": case_id,
                        "event_id": event["event_id"], "introduced_in_version": event["introduced_in_version"],
                        "document": deepcopy(event)})

    def _insert_case(self, case: dict, session):
        self.database.cases.insert_one(self._case_document(case), session=session)
        events = [self._event_document(case["case_id"], event) for event in case["timeline"]]
        if events:
            self.database.clinical_events.insert_many(events, session=session)
        self.database.case_heads.insert_one({"_id": case["case_id"], "version": case["version"]}, session=session)

    @storage_errors
    def seed(self, cases: list[dict]) -> None:
        def write(session):
            for case in cases:
                if self.database.case_heads.find_one({"_id": case["case_id"]}, session=session):
                    continue
                self._insert_case(case, session)
        self._transaction(write)

    @storage_errors
    def cases(self) -> list[dict]:
        pipeline = [
            {"$sort": {"case_id": 1, "version": -1}},
            {"$group": {"_id": "$case_id", "document": {"$first": "$document"}}},
            {"$sort": {"_id": 1}},
        ]
        return [row["document"] for row in self.database.cases.aggregate(pipeline)]

    def _case(self, case_id, version=None, *, session=None):
        query = {"case_id": case_id}
        if version is not None:
            query["version"] = version
        row = self.database.cases.find_one(query, sort=[("version", DESCENDING)], session=session)
        if row is None:
            raise APIError(404, "CASE_NOT_FOUND", "未找到该研究病例或病例版本。")
        return row["document"]

    @storage_errors
    def case(self, case_id: str, version: int | None = None) -> dict:
        return self._case(case_id, version)

    @storage_errors
    def import_history(self) -> list[dict]:
        return [row["document"] for row in self.database.import_batches.find().sort("created_at", -1).limit(50)]

    @storage_errors
    def import_cases(self, cases: list[dict], summary: dict) -> dict:
        def write(session):
            old = self.database.import_batches.find_one({"_id": summary["batch_id"]}, session=session)
            if old:
                return {**old["document"], "already_imported": True}
            inserted, skipped = [], []
            for case in cases:
                old = self.database.cases.find_one({"case_id": case["case_id"], "version": 1}, session=session)
                if old:
                    if old["document"] != case:
                        raise APIError(409, "IMPORT_CASE_CONFLICT", "同一来源病例已有不同内容；本批次未写入，请检查数据版本。")
                    skipped.append(case["case_id"])
                    continue
                self._insert_case(case, session)
                inserted.append(case["case_id"])
            result = {**deepcopy(summary), "created_at": utcnow(), "imported_case_ids": inserted,
                      "skipped_case_ids": skipped, "already_imported": False}
            self.database.import_batches.insert_one(checked({"_id": summary["batch_id"],
                "created_at": result["created_at"], "document": result}), session=session)
            return result
        return self._transaction(write)

    @storage_errors
    def append_event(self, case_id: str, expected_version: int, event: dict,
                     validate: Callable[[dict], dict]) -> dict:
        def write(session):
            case = self._case(case_id, session=session)
            if case["version"] != expected_version:
                raise APIError(409, "CASE_VERSION_CONFLICT", "病例已更新，请刷新后重新提交事件。")
            new_version = expected_version + 1
            created = {**deepcopy(event), "event_id": f"EVT_{uuid4().hex[:16]}",
                "source": "research_scenario_generator", "source_record_id": None,
                "synthetic_extension": True, "confidence": "synthetic", "introduced_in_version": new_version}
            case["version"] = new_version
            case["timeline"].append(created)
            if not any(source["source_name"] == "research_scenario_generator" for source in case["provenance"]):
                case["provenance"].append({"source_name": "research_scenario_generator", "source_url": None,
                    "dataset_version": "research-extensions-v1", "license": "项目自建合成扩展", "synthetic": True})
                if case["case_kind"] == "public_research":
                    case["case_kind"] = "mixed"
            case = validate(case)
            result = self.database.case_heads.update_one({"_id": case_id, "version": expected_version},
                {"$set": {"version": new_version}}, session=session)
            if result.matched_count != 1:
                raise APIError(409, "CASE_VERSION_CONFLICT", "病例已更新，请刷新后重新提交事件。")
            self.database.clinical_events.insert_one(self._event_document(case_id, created), session=session)
            self.database.cases.insert_one(self._case_document(case), session=session)
            return case
        return self._transaction(write)

    @storage_errors
    def create_run(self, snapshot: dict, request: dict, frozen_case: dict) -> None:
        self.database.runs.insert_one(checked({"_id": snapshot["run_id"], "created_at": snapshot["created_at"],
            "status": snapshot["status"], "snapshot": deepcopy(snapshot), "request": deepcopy(request),
            "frozen_case": deepcopy(frozen_case)}))

    def _run_row(self, run_id, *, session=None):
        row = self.database.runs.find_one({"_id": run_id}, session=session)
        if row is None:
            raise APIError(404, "RUN_NOT_FOUND", "未找到该研究运行。")
        return row

    @storage_errors
    def run(self, run_id: str) -> dict:
        return self._run_row(run_id)["snapshot"]

    @storage_errors
    def run_input(self, run_id: str) -> tuple[dict, dict]:
        row = self._run_row(run_id)
        return row["request"], row["frozen_case"]

    @storage_errors
    def runs(self, limit: int = 100, *, active_only: bool = False) -> list[dict]:
        query = {"status": {"$nin": sorted(TERMINAL)}} if active_only else {}
        rows = self.database.runs.find(query).sort("created_at", DESCENDING)
        if not active_only:
            if limit <= 0:
                return []
            rows = rows.limit(limit)
        return [row["snapshot"] for row in rows]

    def _append_audit(self, run_id, event_type, stage, payload, agent_id, update, *, session):
        row = self._run_row(run_id, session=session)
        snapshot = row["snapshot"]
        seq = snapshot["last_seq"] + 1
        event = {"event_id": f"evt_{seq:06d}", "run_id": run_id, "seq": seq,
                 "timestamp": utcnow(), "type": event_type, "stage": stage,
                 "agent_id": agent_id, "payload": deepcopy(payload)}
        update(snapshot, event)
        snapshot["last_seq"] = seq
        snapshot["updated_at"] = event["timestamp"]
        checked({**row, "snapshot": snapshot, "status": snapshot["status"]})
        self.database.audit_events.insert_one(checked({"_id": f"{run_id}:{seq}", "run_id": run_id,
            "seq": seq, "document": event}), session=session)
        result = self.database.runs.update_one({"_id": run_id, "snapshot.last_seq": seq - 1},
            {"$set": {"status": snapshot["status"], "snapshot": snapshot}}, session=session)
        if result.matched_count != 1:
            raise APIError(409, "RUN_VERSION_CONFLICT", "运行状态发生并发变化，请重试。")
        return event, snapshot

    @storage_errors
    def append_audit(self, run_id: str, event_type: str, stage: str, payload: dict,
                     agent_id: str | None, update: Callable[[dict, dict], None]) -> tuple[dict, dict]:
        return self._transaction(lambda session: self._append_audit(
            run_id, event_type, stage, payload, agent_id, update, session=session))

    @storage_errors
    def events(self, run_id: str, after_seq: int = 0, limit: int = 500) -> list[dict]:
        self._run_row(run_id)
        if limit <= 0:
            return []
        return [row["document"] for row in self.database.audit_events.find(
            {"run_id": run_id, "seq": {"$gt": after_seq}}).sort("seq", ASCENDING).limit(limit)]

    @storage_errors
    def complete(self, run_id: str, report: dict, update: Callable[[dict, dict], None]) -> dict:
        def write(session):
            snapshot = self._run_row(run_id, session=session)["snapshot"]
            if snapshot["status"] in TERMINAL or snapshot["cancel_requested"]:
                raise APIError(409, "RUN_NOT_ACTIVE", "运行已经停止，不能保存成功报告。")
            self.database.reports.insert_one(checked({"_id": run_id, "document": deepcopy(report)}), session=session)
            self._append_audit(run_id, "report.generated", "REPORTING", {
                "status": report["status"], "final_decision": report["final_decision"], "metrics": report["metrics"],
            }, None, update, session=session)
            _, snapshot = self._append_audit(run_id, "run.completed", "COMPLETED", {
                "status": report["status"],
            }, None, update, session=session)
            return snapshot
        return self._transaction(write)

    @storage_errors
    def report(self, run_id: str) -> dict:
        snapshot = self._run_row(run_id)["snapshot"]
        if not snapshot["report_ready"]:
            raise APIError(409, "REPORT_NOT_READY", "报告尚未保存，已取消运行不生成报告。")
        row = self.database.reports.find_one({"_id": run_id})
        if row is None:
            raise APIError(500, "REPORT_UNREADABLE", "已保存报告无法读取。")
        return row["document"]

    @storage_errors
    def load_model_settings(self) -> dict:
        return {row["_id"]: row["document"] for row in self.database.model_settings.find()}

    @storage_errors
    def save_model_setting(self, key: str, value: dict) -> None:
        # The caller supplies encrypted credentials; this repository neither
        # decrypts nor exposes provider configuration through public read APIs.
        self.database.model_settings.replace_one({"_id": key}, checked({"_id": key,
            "document": deepcopy(value)}), upsert=True)

    @storage_errors
    def delete_model_setting(self, key: str) -> None:
        self.database.model_settings.delete_one({"_id": key})

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
