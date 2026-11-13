"""Read-only SQLite snapshot migration with content checks and conflict refusal.

Migrate before starting application workers. The SQLite file is never modified.
Mongo writes are one transaction: a conflicting destination record prevents the
whole migration from committing. Repeating a migration with the same input is a
no-op. Reports are split out of run documents to keep MongoDB documents bounded.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from ...api_schemas import APIError
from .mongo import checked, storage_errors

MIGRATION_COLLECTIONS = ("case_heads", "cases", "clinical_events", "runs", "audit_events", "reports", "import_batches", "model_settings")


def _digest(records: dict[str, list[dict]]) -> str:
    normalized = {name: sorted(items, key=lambda item: item["_id"]) for name, items in sorted(records.items())}
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sqlite_snapshot(path: str | Path) -> dict[str, list[dict]]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise APIError(404, "MIGRATION_SOURCE_NOT_FOUND", "未找到待迁移 SQLite 文件。")
    records = {name: [] for name in MIGRATION_COLLECTIONS}
    heads = {}
    try:
        with sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            for row in db.execute("SELECT * FROM cases ORDER BY case_id,version"):
                document = json.loads(row["document"])
                records["cases"].append({"_id": f"{row['case_id']}:{row['version']}", "case_id": row["case_id"],
                                         "version": row["version"], "document": document})
                heads[row["case_id"]] = max(heads.get(row["case_id"], 0), row["version"])
            records["case_heads"] = [{"_id": key, "version": version} for key, version in sorted(heads.items())]
            for row in db.execute("SELECT * FROM clinical_events ORDER BY case_id,event_id"):
                records["clinical_events"].append({"_id": f"{row['case_id']}:{row['event_id']}",
                    "case_id": row["case_id"], "event_id": row["event_id"],
                    "introduced_in_version": row["introduced_in_version"], "document": json.loads(row["document"])})
            for row in db.execute("SELECT * FROM runs ORDER BY run_id"):
                records["runs"].append({"_id": row["run_id"], "created_at": row["created_at"], "status": row["status"],
                    "snapshot": json.loads(row["snapshot"]), "request": json.loads(row["request"]),
                    "frozen_case": json.loads(row["frozen_case"])})
                if row["report"] is not None:
                    records["reports"].append({"_id": row["run_id"], "document": json.loads(row["report"])})
            for row in db.execute("SELECT * FROM audit_events ORDER BY run_id,seq"):
                records["audit_events"].append({"_id": f"{row['run_id']}:{row['seq']}", "run_id": row["run_id"],
                    "seq": row["seq"], "document": json.loads(row["document"])})
            for row in db.execute("SELECT * FROM import_batches ORDER BY batch_id"):
                records["import_batches"].append({"_id": row["batch_id"], "created_at": row["created_at"],
                                                  "document": json.loads(row["document"])})
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_settings'").fetchone():
                for row in db.execute("SELECT * FROM model_settings ORDER BY key"):
                    records["model_settings"].append({"_id": row["key"], "document": json.loads(row["document"])})
    except (sqlite3.Error, json.JSONDecodeError, TypeError):
        raise APIError(422, "MIGRATION_SOURCE_INVALID", "SQLite 源文件结构或记录损坏，未进行迁移。") from None
    for documents in records.values():
        for document in documents:
            checked(document)
    return records


@storage_errors
def migrate_sqlite(sqlite_path: str | Path, mongo_store, *, dry_run: bool = True) -> dict:
    records = sqlite_snapshot(sqlite_path)
    source_digest = _digest(records)
    source_counts = {name: len(items) for name, items in records.items()}

    def migrate(session):
        inserted = Counter({name: 0 for name in records})
        matched = Counter({name: 0 for name in records})
        verified = {name: [] for name in records}
        for name, documents in records.items():
            collection = mongo_store.database[name]
            for document in documents:
                existing = collection.find_one({"_id": document["_id"]}, session=session)
                if existing is not None:
                    if existing != document:
                        # The record key is safe, but do not include source or stored payloads.
                        raise APIError(409, "MIGRATION_CONFLICT", f"MongoDB 的 {name} 已有不同内容；整批未写入，请选择新数据库或先核对。")
                    matched[name] += 1
                    verified[name].append(existing)
                else:
                    inserted[name] += 1
                    if not dry_run:
                        collection.insert_one(document, session=session)
                        persisted = collection.find_one({"_id": document["_id"]}, session=session)
                        if persisted != document:
                            raise APIError(500, "MIGRATION_VERIFY_FAILED", "迁移写入后内容校验失败，已回滚。")
                        verified[name].append(persisted)
        verified_digest = _digest(verified) if not dry_run else None
        if not dry_run and verified_digest != source_digest:
            raise APIError(500, "MIGRATION_VERIFY_FAILED", "迁移内容指纹不一致，已回滚。")
        return {"dry_run": dry_run, "source_counts": source_counts,
                "would_insert" if dry_run else "inserted": dict(inserted), "already_present": dict(matched),
                "source_sha256": source_digest, "verified_sha256": verified_digest,
                "verified": not dry_run and verified_digest == source_digest,
                "source_preserved": True, "database": mongo_store.database.name}

    return mongo_store._transaction(migrate)
