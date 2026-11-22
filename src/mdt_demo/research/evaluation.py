"""Batch paired evaluation, blind reference annotation store, and thesis LaTeX/CSV export."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

from ..api_schemas import APIError
from ..schemas import Decision
from .engine import freeze_context
from .schemas import ResearchCase, Role
from .workflow_designer import evaluate_ablation_matrix

METHOD_ORDER = ("B0", "B1", "B2", "B3", "A1", "A2", "A3", "A4")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BlindAnnotationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: str = Field(min_length=1, max_length=80)
    case_version: int = Field(ge=1, strict=True)
    trigger_event_id: str = Field(min_length=1, max_length=80)
    annotator_id: str = Field(default="annotator_1", min_length=1, max_length=80)
    required_agents: list[Role] = Field(min_length=1, max_length=4)
    expected_decision: Decision
    missing_fields: list[str] = Field(default_factory=list, max_length=30)
    rationale: str = Field(default="", max_length=2000)


class AnnotationStore:
    """Thread-safe local persistence for independent blind reference annotations (Plan §6.1 / G03)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._items: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        tmp = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as fp:
                tmp = Path(fp.name)
                json.dump(self._items, fp, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def list_all(self) -> list[dict]:
        with self._lock:
            return sorted(self._items.values(), key=lambda x: x["scenario_id"])

    def map_all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._items)

    def upsert(self, scenario_id: str, payload: BlindAnnotationInput) -> dict:
        expected_id = f"{payload.case_id}:v{payload.case_version}:{payload.trigger_event_id}"
        if scenario_id != expected_id:
            raise APIError(422, "SCENARIO_ID_MISMATCH", f"场景编号应为 {expected_id}。")
        record = {
            **payload.model_dump(mode="json"),
            "scenario_id": scenario_id,
            "required_agents": list(dict.fromkeys(payload.required_agents)),
            "updated_at": _utcnow(),
        }
        with self._lock:
            self._items[scenario_id] = record
            self._save()
            return record

    def delete(self, scenario_id: str) -> dict:
        with self._lock:
            if scenario_id not in self._items:
                raise APIError(404, "ANNOTATION_NOT_FOUND", "未找到该场景的独立标注记录。")
            del self._items[scenario_id]
            self._save()
            return {"deleted": True, "scenario_id": scenario_id}


def _build_latex_table(method_rows: list[dict], annotated_count: int) -> str:
    has_gold = annotated_count > 0
    header = (
        "方法组 & 角色调用均值 & 节省率 & READY & NEED\\_INFO & DEFER & 专科召回率 & 错误放行率 \\\\"
        if has_gold
        else "方法组 & 策略说明 & 角色调用均值 & 较全员节省 & READY & NEED\\_INFO & DEFER & 门控拦截 \\\\"
    )
    cols = "lrrrrrrr" if has_gold else "llrrrrrr"
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\caption{多智能体 MDT 序贯协同工作流基线对照与单因素消融实验结果（确定性规则仿真）}",
        r"\label{tab:mdt-ablation-results}",
        f"\\begin{{tabular}}{{{cols}}}",
        r"\toprule",
        header,
        r"\midrule",
    ]
    for row in method_rows:
        d = row["decisions"]
        name_tex = row["name"].replace("_", r"\_")
        strat_tex = row["routing_strategy"].replace("_", r"\_")
        if has_gold:
            recall = f"{row['specialist_recall'] * 100:.1f}\\%" if row["specialist_recall"] is not None else "--"
            fp = f"{row['false_pass_rate'] * 100:.1f}\\%" if row["false_pass_rate"] is not None else "--"
            lines.append(
                f"{name_tex} & {row['avg_calls']:.2f} & {row['call_saving_vs_fixed_pct']:.1f}\\% & "
                f"{d['READY_FOR_REVIEW']} & {d['NEED_MORE_INFORMATION']} & {d['DEFER_DECISION']} & {recall} & {fp} \\\\"
            )
        else:
            lines.append(
                f"{name_tex} & {strat_tex} & {row['avg_calls']:.2f} & {row['call_saving_vs_fixed_pct']:.1f}\\% & "
                f"{d['READY_FOR_REVIEW']} & {d['NEED_MORE_INFORMATION']} & {d['DEFER_DECISION']} & {row['gate_interceptions']} \\\\"
            )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])
    return "\n".join(lines)


def _build_scores_csv(scenario_rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "scenario_id", "case_family_id", "case_id", "case_version", "trigger_event_id",
        "trigger_event_type", "visible_events", "method_id", "category", "agent_calls",
        "discussion_rounds", "pre_gate_decision", "final_decision", "missing_count",
        "unresolved_conflicts", "expected_decision",
    ])
    for item in scenario_rows:
        writer.writerow([
            item["scenario_id"], item["case_family_id"], item["case_id"], item["case_version"],
            item["trigger_event_id"], item["trigger_event_type"], item["visible_events"],
            item["method_id"], item["category"], item["agent_calls"], item["discussion_rounds"],
            item["pre_gate_decision"] or "", item["final_decision"] or "",
            item["missing_count"], item["unresolved_conflicts"], item.get("expected_decision") or "",
        ])
    return buf.getvalue()


def evaluate_library(
    cases: list[ResearchCase],
    *,
    trigger_scope: str = "all",
    annotations: dict[str, dict] | None = None,
) -> dict:
    """Run paired 8-arm deterministic evaluations across the selected cases and compute thesis aggregates."""
    if trigger_scope not in {"all", "latest"}:
        raise APIError(422, "INVALID_TRIGGER_SCOPE", "截点范围仅支持 all 或 latest。")
    annotations = annotations or {}
    scenario_rows: list[dict] = []
    scenarios_meta: list[dict] = []

    agg: dict[str, dict] = {}
    memory_impact_count = 0
    families_seen: set[str] = set()

    for case in cases:
        families_seen.add(case.case_id)
        triggers = case.timeline if trigger_scope == "all" else case.timeline[-1:]
        for event in triggers:
            frozen = freeze_context(case, event.event_id)
            scenario_id = f"{case.case_id}:v{case.version}:{event.event_id}"
            ann = annotations.get(scenario_id)
            matrix = evaluate_ablation_matrix(case, event.event_id)

            methods_by_id = {m["method_id"]: m for m in matrix["methods"]}
            if methods_by_id["A1"]["final_decision"] != methods_by_id["B3"]["final_decision"] or (
                methods_by_id["A1"]["missing_count"] != methods_by_id["B3"]["missing_count"]
            ):
                memory_impact_count += 1

            scenarios_meta.append({
                "scenario_id": scenario_id,
                "case_family_id": case.case_id,
                "case_id": case.case_id,
                "case_version": case.version,
                "case_title": case.title,
                "trigger_event_id": event.event_id,
                "trigger_event_title": event.title,
                "trigger_event_type": event.event_type,
                "occurred_at": event.occurred_at.isoformat(),
                "visible_events": len(frozen.timeline),
                "annotated": ann is not None,
                "b3_decision": methods_by_id["B3"]["final_decision"],
                "b3_calls": methods_by_id["B3"]["agent_calls"],
                "fixed_calls": methods_by_id["A3"]["agent_calls"],
            })

            for m in matrix["methods"]:
                mid = m["method_id"]
                bucket = agg.setdefault(mid, {
                    "method_id": mid,
                    "name": m["name"],
                    "category": m["category"],
                    "routing_strategy": m["routing_strategy"],
                    "total_calls": 0,
                    "total_rounds": 0,
                    "decisions": {
                        "READY_FOR_REVIEW": 0,
                        "NEED_MORE_INFORMATION": 0,
                        "DEFER_DECISION": 0,
                        "NO_OUTPUT": 0,
                    },
                    "gate_interceptions": 0,
                    "annotated_count": 0,
                    "recall_sum": 0.0,
                    "false_pass_num": 0,
                    "false_pass_den": 0,
                    "over_defer_num": 0,
                    "over_defer_den": 0,
                    "correct_count": 0,
                })
                bucket["total_calls"] += m["agent_calls"]
                bucket["total_rounds"] += m["discussion_rounds"]
                dec = m["final_decision"] or "NO_OUTPUT"
                bucket["decisions"][dec] = bucket["decisions"].get(dec, 0) + 1
                if m["pre_gate_decision"] == "READY_FOR_REVIEW" and m["final_decision"] != "READY_FOR_REVIEW":
                    bucket["gate_interceptions"] += 1

                if ann is not None:
                    bucket["annotated_count"] += 1
                    req_set = set(ann["required_agents"])
                    sel_set = set(m["selected_agents"])
                    if req_set:
                        bucket["recall_sum"] += len(req_set & sel_set) / len(req_set)
                    exp_dec = ann["expected_decision"]
                    if m["final_decision"] == exp_dec:
                        bucket["correct_count"] += 1
                    if exp_dec in {"NEED_MORE_INFORMATION", "DEFER_DECISION"}:
                        bucket["false_pass_den"] += 1
                        if m["final_decision"] == "READY_FOR_REVIEW":
                            bucket["false_pass_num"] += 1
                    elif exp_dec == "READY_FOR_REVIEW":
                        bucket["over_defer_den"] += 1
                        if m["final_decision"] in {"NEED_MORE_INFORMATION", "DEFER_DECISION"}:
                            bucket["over_defer_num"] += 1

                scenario_rows.append({
                    "scenario_id": scenario_id,
                    "case_family_id": case.case_id,
                    "case_id": case.case_id,
                    "case_version": case.version,
                    "trigger_event_id": event.event_id,
                    "trigger_event_type": event.event_type,
                    "visible_events": len(frozen.timeline),
                    "method_id": mid,
                    "category": m["category"],
                    "agent_calls": m["agent_calls"],
                    "discussion_rounds": m["discussion_rounds"],
                    "pre_gate_decision": m["pre_gate_decision"],
                    "final_decision": m["final_decision"],
                    "missing_count": m["missing_count"],
                    "unresolved_conflicts": m["unresolved_conflicts"],
                    "expected_decision": ann["expected_decision"] if ann else None,
                })

    n_scenarios = max(1, len(scenarios_meta))
    fixed_total_calls = agg.get("A3", {}).get("total_calls", 0)
    annotated_scenarios = sum(1 for s in scenarios_meta if s["annotated"])

    method_summary: list[dict] = []
    for mid in METHOD_ORDER:
        if mid not in agg:
            continue
        b = agg[mid]
        saving = (
            round(100.0 * (fixed_total_calls - b["total_calls"]) / fixed_total_calls, 1)
            if fixed_total_calls > 0 else 0.0
        )
        ann_n = b["annotated_count"]
        method_summary.append({
            "method_id": b["method_id"],
            "name": b["name"],
            "category": b["category"],
            "routing_strategy": b["routing_strategy"],
            "scenario_count": len(scenarios_meta),
            "total_calls": b["total_calls"],
            "avg_calls": round(b["total_calls"] / n_scenarios, 2),
            "avg_discussion_rounds": round(b["total_rounds"] / n_scenarios, 2),
            "call_saving_vs_fixed_pct": saving,
            "decisions": b["decisions"],
            "gate_interceptions": b["gate_interceptions"],
            "annotated_count": ann_n,
            "specialist_recall": round(b["recall_sum"] / ann_n, 4) if ann_n > 0 else None,
            "false_pass_rate": round(b["false_pass_num"] / b["false_pass_den"], 4) if b["false_pass_den"] > 0 else None,
            "over_deferral_rate": round(b["over_defer_num"] / b["over_defer_den"], 4) if b["over_defer_den"] > 0 else None,
            "accuracy": round(b["correct_count"] / ann_n, 4) if ann_n > 0 else None,
        })

    return {
        "protocol_version": "mdt-library-eval-v1",
        "execution_mode": "mock",
        "trigger_scope": trigger_scope,
        "family_count": len(families_seen),
        "scenario_count": len(scenarios_meta),
        "annotated_scenario_count": annotated_scenarios,
        "memory_impact_scenarios": memory_impact_count,
        "methods": method_summary,
        "scenarios": scenarios_meta,
        "latex_table": _build_latex_table(method_summary, annotated_scenarios),
        "scores_csv": _build_scores_csv(scenario_rows),
    }
