"""Real MongoDB replica-set integration checks; never substitute an in-memory fake."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Barrier
from uuid import uuid4

import pytest

from mdt_demo.api_schemas import APIError
from mdt_demo.research.schemas import ResearchCase
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.store import ResearchStore, utcnow

pymongo = pytest.importorskip("pymongo")
from mdt_demo.research.persistence.migration import migrate_sqlite, sqlite_snapshot
from mdt_demo.research.persistence.mongo import MongoResearchStore


@pytest.fixture
def mongo():
    uri = os.environ.get("MDT_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set MDT_TEST_MONGODB_URI to a real MongoDB replica set for storage integration checks")
    name = "mdt_test_" + uuid4().hex
    store = MongoResearchStore(uri, name)
    try:
        yield store
    finally:
        # This database name was generated and created by this fixture only.
        store._client.drop_database(name)
        store.close()


def sample(case_id="CASE-A"):
    document = seed_cases()[0].model_dump(mode="json")
    document["case_id"] = case_id
    return document


def validate(document):
    return ResearchCase.model_validate(document).model_dump(mode="json")


def new_event():
    return {"occurred_at": "2027-01-01", "event_type": "pathology", "title": "Synthetic test event",
            "facts": {"pathology_confirmed": True}}


def new_run(store, run_id="run_test"):
    case = sample()
    now = utcnow()
    snapshot = {"run_id": run_id, "case_id": case["case_id"], "status": "queued", "stage": "QUEUED",
                "created_at": now, "updated_at": now, "last_seq": 0,
                "report_ready": False, "cancel_requested": False, "metrics": {}}
    request = {"case_id": case["case_id"], "case_version": 1, "trigger_event_id": case["timeline"][0]["event_id"]}
    store.create_run(snapshot, request, case)
    return snapshot, request, case


def update(snapshot, event):
    snapshot["stage"] = event["stage"]
    if event["type"] == "report.generated":
        snapshot["report_ready"] = True
        snapshot["metrics"] = event["payload"]["metrics"]
    elif event["type"] == "run.completed":
        snapshot["status"] = event["payload"]["status"]
    elif event["type"] == "run.cancel_requested":
        snapshot["cancel_requested"] = True
        snapshot["status"] = "cancel_requested"


def report():
    return {"run_id": "run_test", "status": "completed", "final_decision": "NEED_MORE_INFORMATION",
            "metrics": {"agent_calls": 2}, "evidence": ["E001:fact"]}


def test_mongo_versions_survive_restart_and_concurrent_append_has_one_winner(mongo):
    first = sample()
    mongo.seed([first])
    other = MongoResearchStore(os.environ["MDT_TEST_MONGODB_URI"], mongo.database.name)
    barrier = Barrier(2)
    def append(store):
        barrier.wait()
        try:
            return store.append_event(first["case_id"], 1, new_event(), validate)
        except APIError as error:
            return error.code
    try:
        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(append, [mongo, other]))
        assert sum(isinstance(value, dict) for value in outcomes) == 1
        assert "CASE_VERSION_CONFLICT" in outcomes
        assert mongo.case(first["case_id"], 1) == first
        latest = other.case(first["case_id"])
        assert latest["version"] == 2
        assert len(latest["timeline"]) == len(first["timeline"]) + 1
        assert mongo.cases() == [latest]
        assert "_id" not in latest
    finally:
        other.close()
    reopened = MongoResearchStore(os.environ["MDT_TEST_MONGODB_URI"], mongo.database.name)
    try:
        assert reopened.case(first["case_id"]) == latest
    finally:
        reopened.close()


def test_mongo_persists_enriched_cutoff_and_original_evidence(mongo, tmp_path):
    from fastapi.testclient import TestClient
    from mdt_demo.api import create_app
    from mdt_demo.research.persistence.config import StorageConfig
    from test_research_api import finish, start

    original = sample("MONGO-ENRICH")
    pathology = {**original["timeline"][0], "event_type": "pathology", "facts": {"histology": "肺腺癌"}}
    later = {**pathology, "event_id": "E002", "facts": {"histology": "肺鳞状细胞癌"}}
    original["timeline"] = [pathology, later]
    mongo.seed([original])
    config = StorageConfig(uri=os.environ["MDT_TEST_MONGODB_URI"], database=mongo.database.name)
    with TestClient(create_app(tmp_path, storage_config=config, event_delay=0)) as client:
        saved = client.post("/api/v2/cases/MONGO-ENRICH/auto-enrich",
                            json={"expected_version": 1, "trigger_event_id": "E001"})
        assert saved.status_code == 201, saved.text
        case = saved.json()["data"]
        first, derived, last = case["timeline"]
        assert first == pathology and last == later and case["version"] == 2
        assert derived["source_fields"] == {"pathology_confirmed": "E001:histology"}
        assert mongo.case("MONGO-ENRICH", 1) == original
        assert mongo.case("MONGO-ENRICH", 2) == case
        stored = mongo.database.clinical_events.find_one({"case_id": "MONGO-ENRICH", "event_id": derived["event_id"]})
        assert stored["document"]["source_fields"] == derived["source_fields"]

        run_id = start(client, case_id="MONGO-ENRICH", case_version=2, trigger_event_id=derived["event_id"])
        assert finish(client, run_id)["report_ready"]
        report = mongo.report(run_id)
        assert report["final_decision"] == "READY_FOR_REVIEW"
        assert report["case_snapshot"]["timeline"] == [first, derived]
        refs = {ref["evidence_id"]: ref for ref in report["evidence_registry"]}
        field = refs[f"{derived['event_id']}:pathology_confirmed"]["source_field"]
        assert refs[field]["value"] == "肺腺癌"


def test_mongo_batch_import_is_idempotent_and_conflict_rolls_back_all_records(mongo):
    case_b = sample("CASE-B")
    batch = mongo.import_cases([case_b], {"batch_id": "batch1"})
    assert batch["imported_case_ids"] == ["CASE-B"]
    assert mongo.import_cases([case_b], {"batch_id": "batch1"})["already_imported"]
    conflicting = deepcopy(case_b)
    conflicting["title"] = "Changed source record"
    with pytest.raises(APIError) as error:
        mongo.import_cases([sample("CASE-A"), conflicting], {"batch_id": "batch2"})
    assert error.value.code == "IMPORT_CASE_CONFLICT"
    with pytest.raises(APIError) as missing:
        mongo.case("CASE-A")
    assert missing.value.code == "CASE_NOT_FOUND"
    assert mongo.database.case_heads.count_documents({}) == 1
    assert len(mongo.import_history()) == 1


def test_mongo_concurrent_audits_have_contiguous_sequences(mongo):
    new_run(mongo)
    other = MongoResearchStore(os.environ["MDT_TEST_MONGODB_URI"], mongo.database.name)
    def append(store):
        for _ in range(8):
            store.append_audit("run_test", "workflow.progress", "ANALYZING", {}, None, update)
    try:
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(append, [mongo, other]))
        events = mongo.events("run_test")
        assert [event["seq"] for event in events] == list(range(1, 17))
        assert mongo.run("run_test")["last_seq"] == 16
        assert mongo.events("run_test", 12, 2) == events[12:14]
    finally:
        other.close()


def test_mongo_report_and_terminal_events_commit_or_rollback_together(mongo):
    before, request, case = new_run(mongo)
    def fail_terminal(snapshot, event):
        update(snapshot, event)
        if event["type"] == "run.completed":
            raise RuntimeError("injected final event failure")
    with pytest.raises(RuntimeError, match="injected"):
        mongo.complete("run_test", report(), fail_terminal)
    assert mongo.run("run_test") == before
    assert mongo.events("run_test") == []
    assert mongo.database.reports.count_documents({}) == 0
    assert mongo.run_input("run_test") == (request, case)
    with pytest.raises(APIError) as error:
        mongo.report("run_test")
    assert error.value.code == "REPORT_NOT_READY"
    completed = mongo.complete("run_test", report(), update)
    assert completed["status"] == "completed" and completed["report_ready"]
    assert mongo.report("run_test") == report()
    assert [event["type"] for event in mongo.events("run_test")] == ["report.generated", "run.completed"]
    assert mongo.runs(active_only=True) == []
    with pytest.raises(APIError) as repeated:
        mongo.complete("run_test", report(), update)
    assert repeated.value.code == "RUN_NOT_ACTIVE"


def test_mongo_cancelled_run_never_gets_report(mongo):
    new_run(mongo)
    mongo.append_audit("run_test", "run.cancel_requested", "QUEUED", {}, None, update)
    with pytest.raises(APIError) as error:
        mongo.complete("run_test", report(), update)
    assert error.value.code == "RUN_NOT_ACTIVE"
    assert mongo.database.reports.count_documents({}) == 0


def test_mongo_model_settings_are_separate_from_case_and_run_payloads(mongo):
    encrypted = {"base_url": "https://provider.example/v1", "api_key_ciphertext": "opaque-ciphertext"}
    mongo.save_model_setting("oncology", encrypted)
    assert mongo.load_model_settings() == {"oncology": encrypted}
    mongo.save_model_setting("oncology", {**encrypted, "model": "model-b"})
    assert mongo.load_model_settings()["oncology"]["model"] == "model-b"
    assert mongo.cases() == [] and mongo.runs() == []
    mongo.delete_model_setting("oncology")
    assert mongo.load_model_settings() == {}


def test_mongo_large_document_rejected_before_write(mongo, monkeypatch):
    monkeypatch.setattr("mdt_demo.research.persistence.mongo.MAX_DOCUMENT_BYTES", 500)
    with pytest.raises(APIError) as error:
        new_run(mongo)
    assert error.value.code == "STORAGE_DOCUMENT_TOO_LARGE"
    assert mongo.runs() == []


def sqlite_source(path):
    source = ResearchStore(path)
    original = sample()
    source.seed([original])
    source.append_event(original["case_id"], 1, new_event(), validate)
    new_run(source)
    source.append_audit("run_test", "run.started", "INITIALIZING", {}, None, update)
    source.complete("run_test", report(), update)
    source.import_cases([sample("IMPORTED")], {"batch_id": "batch_migration"})
    source.close()


def test_sqlite_migration_preserves_all_records_verifies_and_is_repeatable(mongo, tmp_path):
    source_path = tmp_path / "source.sqlite3"
    sqlite_source(source_path)
    before = sqlite_snapshot(source_path)
    preview = migrate_sqlite(source_path, mongo)
    assert preview["dry_run"] and preview["would_insert"]["cases"] == 3
    assert mongo.cases() == []
    result = migrate_sqlite(source_path, mongo, dry_run=False)
    assert result["verified"] and result["source_sha256"] == result["verified_sha256"]
    assert result["source_counts"]["audit_events"] == 3
    assert mongo.case("CASE-A")["version"] == 2
    assert mongo.case("CASE-A", 1) == sample()
    assert mongo.report("run_test") == report()
    assert len(mongo.import_history()) == 1
    repeated = migrate_sqlite(source_path, mongo, dry_run=False)
    assert repeated["verified"] and sum(repeated["inserted"].values()) == 0
    assert sqlite_snapshot(source_path) == before


def test_migration_destination_conflict_rolls_back_before_partial_import(mongo, tmp_path):
    source_path = tmp_path / "source.sqlite3"
    sqlite_source(source_path)
    conflicting = sample("IMPORTED")
    conflicting["title"] = "Different destination data"
    mongo.seed([conflicting])
    with pytest.raises(APIError) as error:
        migrate_sqlite(source_path, mongo, dry_run=False)
    assert error.value.code == "MIGRATION_CONFLICT"
    assert mongo.cases() == [conflicting]
    assert mongo.runs() == []
    assert mongo.database.audit_events.count_documents({}) == 0


def test_mongo_application_import_run_audit_and_settings_survive_restart(mongo, tmp_path):
    from fastapi.testclient import TestClient
    from mdt_demo.api import create_app
    from mdt_demo.research.persistence.config import StorageConfig
    from test_research_api import finish, start
    import json

    config = StorageConfig(uri=os.environ["MDT_TEST_MONGODB_URI"], database=mongo.database.name)
    with TestClient(create_app(tmp_path, storage_config=config, event_delay=0)) as client:
        assert client.get("/api/v2/storage").json()["data"]["backend"] == "mongodb"
        raw = json.dumps({"cases": [sample("MONGO-IMPORT")]}).encode()
        preview = client.post("/api/v2/datasets/preview?source=research_json", content=raw,
                              headers={"Content-Type": "application/octet-stream"})
        assert preview.status_code == 200, preview.text
        preview_id = preview.json()["data"]["preview_id"]
        batch = client.post(f"/api/v2/datasets/import/{preview_id}")
        assert batch.status_code == 200, batch.text
        assert batch.json()["data"]["imported_case_ids"] == ["MONGO-IMPORT"]
        run_id = start(client, case_id="MONGO-IMPORT")
        run = finish(client, run_id)
        assert run["report_ready"]
        report = client.get(f"/api/v2/runs/{run_id}/report").json()["data"]
        events = client.get(f"/api/v2/runs/{run_id}/audit").json()["data"]["events"]
        saved = client.put("/api/v2/settings/agents/oncology", json={"model": "mongo-test", "api_key": "mongo-secret-fixture"})
        assert saved.status_code == 200
        assert "mongo-secret-fixture" not in json.dumps(mongo.load_model_settings())
    with TestClient(create_app(tmp_path, storage_config=config, event_delay=0)) as client:
        assert client.get("/api/v2/settings/agents/oncology").json()["data"]["has_api_key"]
        assert client.get(f"/api/v2/runs/{run_id}/report").json()["data"] == report
        assert client.get(f"/api/v2/runs/{run_id}").json()["data"] == run
        stream = client.get(f"/api/v2/runs/{run_id}/events?after_seq=3")
        assert [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")] == events[3:]
        assert len(client.get("/api/v2/datasets").json()["data"]["batches"]) == 1
    assert not (tmp_path / "research.sqlite3").exists()


def test_mongo_configuration_fails_closed_without_silent_sqlite(tmp_path):
    from mdt_demo.research.persistence.config import StorageConfig, create_repository
    with pytest.raises(APIError, match="STORAGE_INVALID_BACKEND"):
        create_repository(StorageConfig(backend="typo"), tmp_path)
    with pytest.raises(APIError, match="MONGODB_CONNECTION_FAILED"):
        MongoResearchStore("mongodb://127.0.0.1:1", timeout_ms=100)
    assert not (tmp_path / "research.sqlite3").exists()
