"""Run paired, deterministic research-workflow comparisons from local data."""

import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from pydantic import __version__ as pydantic_version

from mdt_demo import schemas as base_schemas
from mdt_demo.api_schemas import APIError
from mdt_demo.research import datasets, engine, schemas, seeds, workflow_designer
from mdt_demo.research.schemas import ResearchCase


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def load_cases(source, input_file, limit):
    if source == "seed":
        cases = seeds.seed_cases()[:limit]
        return cases, {"source": source, "dataset_version": seeds.VERSION, "requested_limit": limit}
    with input_file.open("rb") as stream:
        raw = stream.read(datasets.MAX_UPLOAD_BYTES + 1)
    prepared = datasets.prepare_import(source, raw, limit)
    return [ResearchCase.model_validate(item) for item in prepared.cases], prepared.summary


def plan_batch(cases, dataset, trigger_scope):
    family_records, scenarios = [], []
    for case in cases:
        family_records.append({
            "case_family_id": case.case_id, "case_id": case.case_id, "case_version": case.version,
            "case_kind": case.case_kind, "case_sha256": digest(case.model_dump(mode="json")),
            "unplaced_record_count": len(case.unplaced_records),
            "provenance": [item.model_dump(mode="json") for item in case.provenance],
        })
        triggers = case.timeline if trigger_scope == "all" else case.timeline[-1:]
        for event in triggers:
            frozen = engine.freeze_context(case, event.event_id)
            scenarios.append({
                "scenario_id": f"{case.case_id}:v{case.version}:{event.event_id}",
                "case_family_id": case.case_id, "case_id": case.case_id, "case_version": case.version,
                "trigger_event_id": event.event_id, "trigger_event_type": event.event_type,
                "cutoff_date": event.occurred_at.isoformat(), "visible_event_count": len(frozen.timeline),
                "visible_fact_count": sum(len(item.facts) for item in frozen.timeline),
                "frozen_input_sha256": digest(frozen.model_dump(mode="json")),
            })

    modules = (base_schemas, datasets, engine, schemas, seeds, workflow_designer, sys.modules[__name__])
    return {
        "protocol": "mdt-mock-batch-v1", "mode": "mock", "mock_scenario": "standard",
        "trigger_scope": trigger_scope, "cutoff_order": ["occurred_at", "event_id"],
        "dataset": dataset, "families": family_records, "scenarios": scenarios,
        "implementation_sha256": {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                  for module in modules},
        "runtime": {"python": sys.version.split()[0], "pydantic": pydantic_version},
    }


def bind_plan(db, plan):
    with db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS manifest (id INTEGER PRIMARY KEY CHECK (id=1), plan TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS attempts (
            scenario_id TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL,
            result TEXT NOT NULL, PRIMARY KEY (scenario_id, attempt))""")
        previous = db.execute("SELECT plan FROM manifest WHERE id=1").fetchone()
        serialized = encoded(plan)
        if previous is None:
            db.execute("INSERT INTO manifest VALUES (1, ?)", (serialized,))
        elif previous[0] != serialized:
            raise ValueError("该目录已绑定其他输入、截点范围或实现版本。请为新批次指定新的输出目录。")


def run_scenario(db, case, scenario):
    scenario_id = scenario["scenario_id"]
    with db:
        db.execute("BEGIN IMMEDIATE")
        latest = db.execute("SELECT attempt, status FROM attempts WHERE scenario_id=? ORDER BY attempt DESC LIMIT 1",
                            (scenario_id,)).fetchone()
        if latest and latest[1] == "completed":
            return
        attempt = latest[0] + 1 if latest else 1
        try:
            trigger = scenario["trigger_event_id"]
            result = workflow_designer.evaluate_ablation_matrix(case, trigger)
        except Exception as error:
            # Keep other scenarios runnable. Exclude source values from the error record.
            status, result = "failed", {"error_type": type(error).__name__}
            if isinstance(error, (engine.WorkflowError, APIError)):
                result["error_code"] = error.code
        else:
            status = "completed"
        db.execute("INSERT INTO attempts VALUES (?, ?, ?, ?)", (scenario_id, attempt, status, encoded(result)))


def export_results(db, plan, output_dir):
    with db:
        db.execute("BEGIN IMMEDIATE")
        attempts = [
            {"scenario_id": key, "attempt": number, "status": status, "result": json.loads(payload)}
            for key, number, status, payload in db.execute(
                "SELECT scenario_id, attempt, status, result FROM attempts ORDER BY scenario_id, attempt")
        ]
        latest = {row["scenario_id"]: row for row in attempts}
        complete = [row for row in latest.values() if row["status"] == "completed"]
        summary = {
            "families": len(plan["families"]), "scenarios": len(plan["scenarios"]),
            "completed": len(complete), "failed": sum(row["status"] == "failed" for row in latest.values()),
            "method_rows": sum(len(row["result"]["methods"]) for row in complete),
        }
        export = {"manifest_sha256": digest(plan), "manifest": plan, "summary": summary, "attempts": attempts}
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=output_dir, delete=False) as file:
                temporary = Path(file.name)
                json.dump(export, file, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
                file.write("\n")
            os.replace(temporary, output_dir / "results.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return summary
