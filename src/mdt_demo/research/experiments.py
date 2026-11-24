"""Run paired, deterministic research-workflow comparisons from local data."""

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile

from pydantic import ValidationError, __version__ as pydantic_version

from mdt_demo import schemas as base_schemas
from mdt_demo.api_schemas import APIError
from mdt_demo.research import blind_review, datasets, engine, evaluation, schemas, seeds, workflow_designer
from mdt_demo.research.schemas import ResearchCase


SCENARIO_ID = re.compile(r"([A-Za-z0-9_-]{1,80}):v([1-9][0-9]*):([A-Za-z0-9_-]{1,80})")


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


def _unique_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("标注 JSON 含有重复键，请核对导出文件。")
        result[key] = value
    return result


def load_annotations_file(path: Path | None) -> dict[str, dict]:
    """Validate keyed JSON, list JSON, and JSONL (adjudication.jsonl) annotation exports."""
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        raw = [
            json.loads(line, object_pairs_hook=_unique_json_keys)
            for line in text.splitlines()
            if line.strip()
        ]
    else:
        raw = json.loads(text, object_pairs_hook=_unique_json_keys)
    if isinstance(raw, dict) and "items" in raw:
        raw = raw["items"]
        if not isinstance(raw, list):
            raise ValueError("标注文件的 items 必须是数组。")
    if isinstance(raw, dict):
        entries = raw.items()
    elif isinstance(raw, list):
        entries = ((None, item) for item in raw)
    else:
        raise ValueError("标注文件格式无效，应为 JSON 对象、数组或 JSONL。")

    annotations = {}
    ignored_extra = {
        "scenario_id", "updated_at", "created_at", "protocol_version",
        "expected_conflicts", "resolved_from_annotators", "source_disagreement_types",
        "reference_source", "adjudicator_id", "adjudication_rationale",
    }
    for index, (key, item) in enumerate(entries, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条标注必须是对象。")
        sid = item.get("scenario_id", key)
        match = SCENARIO_ID.fullmatch(sid) if isinstance(sid, str) else None
        if not match or (key is not None and key != sid):
            raise ValueError(f"第 {index} 条标注缺少有效的场景编号或与对象键不一致。")
        if sid in annotations:
            raise ValueError(f"第 {index} 条标注重复使用了同一场景编号。")
        # Early keyed exports kept only the scoring fields and encoded identity in the key.
        case_id, version, event_id = match.groups()
        identity = {"case_id": case_id, "case_version": int(version), "trigger_event_id": event_id}
        payload = {**identity, **{k: v for k, v in item.items() if k not in ignored_extra}}
        if "adjudicator_id" in item and "annotator_id" not in payload:
            payload["annotator_id"] = item["adjudicator_id"]
        if "adjudication_rationale" in item and "rationale" not in payload:
            payload["rationale"] = item["adjudication_rationale"]
        try:
            validated = evaluation.BlindAnnotationInput.model_validate(payload).model_dump(mode="json")
        except ValidationError:
            raise ValueError(f"第 {index} 条标注不符合独立标注契约，请核对字段、专科和流程标签。") from None
        if any(validated[k] != value for k, value in identity.items()):
            raise ValueError(f"第 {index} 条标注的病例版本或触发事件与场景编号不一致。")
        annotations[sid] = {**validated, "scenario_id": sid}
    return annotations


def _atomic_write_text(target: Path, text: str) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as fp:
            temporary = Path(fp.name)
            fp.write(text)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_checkpoint_paper(db, plan, cases, annotations, output_dir: Path) -> dict[str, str]:
    """Score the recorded matrices and serialize concurrent exports to the same directory."""
    with db:
        db.execute("BEGIN IMMEDIATE")
        matrices = {sid: json.loads(result) for sid, result in db.execute(
            "SELECT scenario_id, result FROM attempts WHERE status='completed'")}
        if matrices.keys() != {row["scenario_id"] for row in plan["scenarios"]}:
            raise ValueError("计划截点仍有失败或尚未执行，请先续跑，完成后再导出论文产物。")
        selected_annotations = {sid: item for sid, item in annotations.items() if sid in matrices}
        scores = evaluation.evaluate_library(cases, trigger_scope=plan["trigger_scope"],
                                             annotations=selected_annotations, matrices=matrices)
        with (output_dir / "results.json").open("rb") as result_file:
            results_hash = hashlib.file_digest(result_file, "sha256").hexdigest()
        provenance = {
            "manifest_sha256": digest(plan),
            "results_sha256": results_hash,
            "evaluator_sha256": hashlib.sha256(Path(evaluation.__file__).read_bytes()).hexdigest(),
            "reference_validation_sha256": hashlib.sha256(Path(blind_review.__file__).read_bytes()).hexdigest(),
            "scored_annotations_sha256": digest(selected_annotations),
            "annotations_with_input_sha256": sum(
                item.get("input_sha256") is not None for item in selected_annotations.values()),
            "annotations_outside_scope": len(annotations) - len(selected_annotations),
        }
        return export_paper_artifacts(output_dir, scores, provenance)


def export_paper_artifacts(output_dir: Path, evaluation: dict, provenance: dict | None = None) -> dict[str, str]:
    """Write data first and publish their fingerprints in the statistics file last."""
    scores_path = output_dir / "scores.csv"
    latex_path = output_dir / "ablation_table.tex"
    error_path = output_dir / "error_analysis.csv"
    stats_path = output_dir / "statistics_summary.json"
    _atomic_write_text(scores_path, evaluation["scores_csv"])
    _atomic_write_text(latex_path, evaluation["latex_table"] + "\n")
    _atomic_write_text(error_path, evaluation.get("error_analysis_csv", ""))
    summary_payload = {
        "provenance": {
            **(provenance or {}),
            "scores_csv_sha256": hashlib.sha256(scores_path.read_bytes()).hexdigest(),
            "latex_table_sha256": hashlib.sha256(latex_path.read_bytes()).hexdigest(),
            "error_analysis_csv_sha256": hashlib.sha256(error_path.read_bytes()).hexdigest(),
        },
        "protocol_version": evaluation["protocol_version"],
        "execution_mode": evaluation["execution_mode"],
        "trigger_scope": evaluation["trigger_scope"],
        "family_count": evaluation["family_count"],
        "scenario_count": evaluation["scenario_count"],
        "annotated_scenario_count": evaluation["annotated_scenario_count"],
        "memory_impact_scenarios": evaluation["memory_impact_scenarios"],
        "methods": evaluation["methods"],
        "paired_statistics": evaluation["paired_statistics"],
        "error_analysis_count": len(evaluation.get("error_analysis", [])),
    }
    _atomic_write_text(
        stats_path,
        json.dumps(summary_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        "scores_csv": str(scores_path),
        "latex_table": str(latex_path),
        "error_analysis_csv": str(error_path),
        "statistics_summary": str(stats_path),
    }
