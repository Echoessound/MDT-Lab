"""Batch paired evaluation, blind reference annotation store, and thesis LaTeX/CSV export."""

from __future__ import annotations

from collections.abc import Callable
import csv
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import random
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..api_schemas import APIError
from ..schemas import Decision
from .blind_review import material_from_frozen, validate_reference
from .engine import _review_input, freeze_context
from .schemas import ResearchCase, Role
from .workflow_designer import evaluate_ablation_matrix, infer_semantic_completeness

METHOD_ORDER = ("B0", "B1", "B2", "B3", "A1", "A2", "A3", "A4")
THREE_CLASSES = ("READY_FOR_REVIEW", "NEED_MORE_INFORMATION", "DEFER_DECISION")
PRED_CLASSES = ("READY_FOR_REVIEW", "NEED_MORE_INFORMATION", "DEFER_DECISION", "NO_OUTPUT")


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
    input_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_ids: list[Annotated[str, Field(min_length=3, max_length=161)]] = Field(default_factory=list, max_length=80)
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

    def _save(self, items: dict[str, dict]) -> None:
        tmp = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as fp:
                tmp = Path(fp.name)
                json.dump(items, fp, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
            self._items = items
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def list_all(self) -> list[dict]:
        with self._lock:
            return sorted(self._items.values(), key=lambda x: x["scenario_id"])

    def map_all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._items)

    def own(self, scenario_id: str, annotator_id: str) -> dict | None:
        with self._lock:
            item = self._items.get(scenario_id)
            return item if item and item["annotator_id"] == annotator_id else None

    def _check_reviewer(self, scenario_id: str, annotator_id: str) -> None:
        existing = self._items.get(scenario_id)
        if existing and existing["annotator_id"] != annotator_id:
            raise APIError(409, "ANNOTATION_REVIEWER_CONFLICT", "该截点已有其他编号的参考标注。")

    def upsert(self, scenario_id: str, payload: BlindAnnotationInput) -> dict:
        expected_id = f"{payload.case_id}:v{payload.case_version}:{payload.trigger_event_id}"
        if scenario_id != expected_id:
            raise APIError(422, "SCENARIO_ID_MISMATCH", f"场景编号应为 {expected_id}。")
        record = {
            **payload.model_dump(mode="json"),
            "scenario_id": scenario_id,
            "required_agents": list(dict.fromkeys(payload.required_agents)),
            "evidence_ids": list(dict.fromkeys(payload.evidence_ids)),
            "updated_at": _utcnow(),
        }
        with self._lock:
            self._check_reviewer(scenario_id, payload.annotator_id)
            self._save({**self._items, scenario_id: record})
            return record

    def delete(self, scenario_id: str, annotator_id: str | None = None) -> dict:
        with self._lock:
            if scenario_id not in self._items:
                raise APIError(404, "ANNOTATION_NOT_FOUND", "未找到该场景的独立标注记录。")
            if annotator_id is not None:
                self._check_reviewer(scenario_id, annotator_id)
            remaining = dict(self._items)
            del remaining[scenario_id]
            self._save(remaining)
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
        "unresolved_conflicts", "expected_decision", "selected_agents", "required_agents",
        "required_agent_hits", "required_agent_count",
        "input_case_version", "input_trigger_event_id", "method_visible_events", "trajectory_id",
    ])
    for item in scenario_rows:
        writer.writerow([
            item["scenario_id"], item["case_family_id"], item["case_id"], item["case_version"],
            item["trigger_event_id"], item["trigger_event_type"], item["visible_events"],
            item["method_id"], item["category"], item["agent_calls"], item["discussion_rounds"],
            item["pre_gate_decision"] or "", item["final_decision"] or "",
            item["missing_count"], item["unresolved_conflicts"], item.get("expected_decision") or "",
            json.dumps(item["selected_agents"], ensure_ascii=False),
            json.dumps(item["required_agents"], ensure_ascii=False) if item["required_agents"] is not None else "",
            item["required_agent_hits"], item["required_agent_count"],
            item["input_case_version"], item["input_trigger_event_id"],
            item["method_visible_events"], item["trajectory_id"],
        ])
    return buf.getvalue()


def _compute_macro_f1(cm: dict[str, dict[str, int]]) -> float | None:
    """Compute unweighted Macro-F1 across present gold classes in the 3-class confusion matrix."""
    f1_scores: list[float] = []
    for cls in THREE_CLASSES:
        support = sum(cm[cls].values())
        if support == 0:
            continue
        tp = cm[cls][cls]
        fp = sum(cm[other][cls] for other in THREE_CLASSES if other != cls)
        fn = support - tp
        denom = 2 * tp + fp + fn
        f1_scores.append((2 * tp / denom) if denom > 0 else 0.0)
    return round(sum(f1_scores) / len(f1_scores), 4) if f1_scores else None


def _build_error_analysis_csv(error_rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "scenario_id", "case_family_id", "trigger_event_type", "method_id",
        "error_types", "expected_decision", "predicted_decision",
        "required_agents", "selected_agents", "missed_agents",
        "missing_count", "unresolved_conflicts", "root_cause_hint",
    ])
    for item in error_rows:
        writer.writerow([
            item["scenario_id"], item["case_family_id"], item["trigger_event_type"],
            item["method_id"], "|".join(item["error_types"]),
            item["expected_decision"], item["predicted_decision"] or "NO_OUTPUT",
            json.dumps(item["required_agents"], ensure_ascii=False),
            json.dumps(item["selected_agents"], ensure_ascii=False),
            json.dumps(item["missed_agents"], ensure_ascii=False),
            item["missing_count"], item["unresolved_conflicts"], item["root_cause_hint"],
        ])
    return buf.getvalue()


def _error_root_cause(error_types: list[str], method: dict, missed_agents: list[str]) -> str:
    hints: list[str] = []
    if "no_output" in error_types:
        hints.append("有效最终意见为零，无可用流程输出")
    if "false_pass" in error_types:
        if not method.get("gate_applied", True):
            hints.append("未启用安全门控，相对多数聚合在缺件或分歧下错误放行")
        else:
            hints.append("系统规则未将参考标注认定的缺件或风险纳入阻断条件")
    if "over_deferral" in error_types:
        if method["unresolved_conflicts"] > 0:
            hints.append("存在未解决分歧，安全门控保守暂缓")
        elif method["missing_count"] > 0:
            hints.append("规则判定必需字段缺失，门控要求补件")
        else:
            hints.append("专科或门控策略较参考标注更保守")
    if "missed_specialist" in error_types:
        hints.append(f"当前路由规则未调度必要专科：{', '.join(missed_agents)}")
    if not hints:
        hints.append("预测流程标签与参考标注不一致（补件与暂缓边界差异）")
    return "；".join(hints)


def _mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact binomial p-value for independent paired correctness outcomes."""
    if b == c:
        return 1.0
    n = b + c
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, (2 * tail) / (2 ** n))


def _paired_accuracy_test(records: list[dict], comparator_key: str) -> dict:
    annotated = [item for item in records if item["expected_decision"] is not None]
    families = {item["case_family_id"] for item in annotated}
    b3_only = comparator_only = 0
    for item in annotated:
        b3_ok = item["b3_decision"] == item["expected_decision"]
        comparator_ok = item[comparator_key] == item["expected_decision"]
        b3_only += b3_ok and not comparator_ok
        comparator_only += comparator_ok and not b3_ok

    status = "ok"
    if not annotated:
        status = "no_annotations"
    elif len(families) != len(annotated):
        status = "repeated_family"
    return {
        "mcnemar_status": status,
        "annotated_pairs": len(annotated),
        "b3_only_correct": b3_only,
        "comparator_only_correct": comparator_only,
        "mcnemar_exact_p": _mcnemar_exact_p(b3_only, comparator_only) if status == "ok" else None,
    }


def _cluster_ratio_ci(
    counts_by_family: dict[str, tuple[int, int]],
    n_bootstrap: int,
    seed: int,
) -> tuple[float | None, float | None]:
    """Resample contributing families, retaining all eligible cutoffs in each draw."""
    if len(counts_by_family) < 2:
        return None, None
    counts = [counts_by_family[key] for key in sorted(counts_by_family)]
    rng = random.Random(seed)
    samples = []
    for _ in range(n_bootstrap):
        numerator = denominator = 0
        for hits, total in rng.choices(counts, k=len(counts)):
            numerator += hits
            denominator += total
        samples.append(100 * numerator / denominator)
    samples.sort()
    # Nearest-rank percentiles of the empirical bootstrap distribution.
    return (
        round(samples[math.ceil(0.025 * n_bootstrap) - 1], 2),
        round(samples[math.ceil(0.975 * n_bootstrap) - 1], 2),
    )


def _build_paired_statistics(
    paired_records: list[dict],
    *,
    n_bootstrap: int = 1000,
    seed: int = 2026,
) -> dict:
    family_count = len({item["case_family_id"] for item in paired_records})

    def contrast(
        comparator: str,
        label: str,
        metric_name: str,
        interpretation: str,
        counts: Callable[[dict], tuple[int, int]],
    ) -> dict:
        family_totals: dict[str, tuple[int, int]] = {}
        eligible = discordant = 0
        for item in paired_records:
            numerator, denominator = counts(item)
            if denominator == 0:
                continue
            eligible += 1
            discordant += numerator > 0
            family = item["case_family_id"]
            hits, total = family_totals.get(family, (0, 0))
            family_totals[family] = (hits + numerator, total + denominator)

        numerator = sum(hits for hits, _ in family_totals.values())
        denominator = sum(total for _, total in family_totals.values())
        low, high = _cluster_ratio_ci(family_totals, n_bootstrap, seed)
        return {
            "contrast_id": f"B3_vs_{comparator}",
            "label": label,
            "metric_name": metric_name,
            "interpretation": interpretation,
            "unit": "%",
            "metric_numerator": numerator,
            "metric_denominator": denominator,
            "point_estimate": round(100 * numerator / denominator, 2) if denominator else None,
            "ci_low": low,
            "ci_high": high,
            "eligible_family_count": len(family_totals),
            "eligible_scenarios": eligible,
            "discordant_scenarios": discordant,
            "total_scenarios": len(paired_records),
            **_paired_accuracy_test(paired_records, f"{comparator.lower()}_decision"),
        }

    contrasts = [
        contrast(
            "A3", "B3 事件路由 vs A3 固定全员", "专科调用节省比例",
            "节省的角色调用总数除以 A3 固定全员的角色调用总数，包含讨论轮次。",
            lambda r: (r["a3_calls"] - r["b3_calls"], r["a3_calls"]),
        ),
        contrast(
            "B2", "B3 完整门控 vs B2 门控前", "门控前拟放行截点的拦截比例",
            "分母为 B2 在共享审阅轨迹上拟放行的截点，分子为 B3 将其改判为补件或暂缓的截点。",
            lambda r: (
                r["b2_decision"] == "READY_FOR_REVIEW" and
                r["b3_decision"] in {"NEED_MORE_INFORMATION", "DEFER_DECISION"},
                r["b2_decision"] == "READY_FOR_REVIEW",
            ),
        ),
        contrast(
            "A1", "B3 含纵向记忆 vs A1 仅当前事件", "纵向记忆影响截点比例",
            "分母为全部配对截点，分子为保留历史后流程标签或缺失字段数发生变化的截点。",
            lambda r: (r["memory_impacted"], 1),
        ),
        contrast(
            "A2", "B3 原始输入 vs A2 语义补齐扩展", "语义补齐后标签变化比例",
            "分母为全部配对截点。A2 可追加可溯源的派生事件，正确性检验衡量对原截点盲标的符合程度。"
            "扩展截点的独立正确率需要该扩展材料的参考标注。",
            lambda r: (r["b3_decision"] != r["a2_decision"], 1),
        ),
        contrast(
            "B0", "B3 完整 MDT vs B0 单审阅者", "相对单审阅者的标签差异率",
            "分母为全部配对截点，分子为 B3 与 B0 最终流程标签不同的截点。",
            lambda r: (r["b3_decision"] != r["b0_decision"], 1),
        ),
    ]
    sample_note = (
        f"共 {family_count} 个病例族、{len(paired_records)} 个截点。各指标按可评病例族整体重抽样，"
        "少于两个可评病例族时仅提供点估计。McNemar 检验比较对独立参考标签的判断正确性，"
        "每个带标注病例族仅含一个带标注截点时可计算。"
    )
    if family_count < 5:
        sample_note += "当前病例族较少，区间仅供描述本批样本。"
    return {
        "bootstrap_resamples": n_bootstrap,
        "bootstrap_seed": seed,
        "cluster_unit": "case_family_id",
        "family_count": family_count,
        "sample_size_note": sample_note,
        "contrasts": contrasts,
    }


def evaluate_library(
    cases: list[ResearchCase],
    *,
    trigger_scope: str = "all",
    annotations: dict[str, dict] | None = None,
    matrices: dict[str, dict] | None = None,
    case_family_map: dict[str, str] | None = None,
) -> dict:
    """Run paired 8-arm deterministic evaluations across the selected cases and compute thesis aggregates."""
    if trigger_scope not in {"all", "latest"}:
        raise APIError(422, "INVALID_TRIGGER_SCOPE", "截点范围仅支持 all 或 latest。")
    annotations = annotations or {}
    scenario_rows: list[dict] = []
    scenarios_meta: list[dict] = []
    paired_records: list[dict] = []
    error_rows: list[dict] = []

    agg: dict[str, dict] = {}
    memory_impact_count = 0
    families_seen: set[str] = set()

    for case in cases:
        family_id = (case_family_map or {}).get(case.case_id, case.case_id)
        families_seen.add(family_id)
        triggers = case.timeline if trigger_scope == "all" else case.timeline[-1:]
        for event in triggers:
            scenario_id = f"{case.case_id}:v{case.version}:{event.event_id}"
            ann = annotations.get(scenario_id)
            frozen = freeze_context(case, event.event_id)
            if ann is not None:
                validate_reference(material_from_frozen(frozen), ann)
            matrix = (evaluate_ablation_matrix(case, event.event_id) if matrices is None
                      else matrices[scenario_id])
            frozen_missing = set(_review_input(frozen)["missing_information"])
            trigger_only_missing = set(
                _review_input(frozen.model_copy(update={"timeline": [frozen.timeline[-1]]}))["missing_information"]
            )
            semantic_missing = set(infer_semantic_completeness(frozen, event.event_id)["post_inference_missing"])

            methods_by_id = {m["method_id"]: m for m in matrix["methods"]}
            memory_impacted = (
                methods_by_id["A1"]["final_decision"] != methods_by_id["B3"]["final_decision"]
                or methods_by_id["A1"]["missing_count"] != methods_by_id["B3"]["missing_count"]
            )
            if memory_impacted:
                memory_impact_count += 1

            b3_m = methods_by_id["B3"]
            a3_m = methods_by_id["A3"]
            paired_records.append({
                "scenario_id": scenario_id,
                "case_family_id": family_id,
                "b3_calls": b3_m["agent_calls"],
                "a3_calls": a3_m["agent_calls"],
                "b3_decision": b3_m["final_decision"],
                "a3_decision": a3_m["final_decision"],
                "b2_decision": methods_by_id["B2"]["final_decision"],
                "a2_decision": methods_by_id["A2"]["final_decision"],
                "a1_decision": methods_by_id["A1"]["final_decision"],
                "b0_decision": methods_by_id["B0"]["final_decision"],
                "memory_impacted": memory_impacted,
                "expected_decision": ann["expected_decision"] if ann else None,
            })

            scenarios_meta.append({
                "scenario_id": scenario_id,
                "case_family_id": family_id,
                "case_id": case.case_id,
                "case_version": case.version,
                "case_title": case.title,
                "trigger_event_id": event.event_id,
                "trigger_event_title": event.title,
                "trigger_event_type": event.event_type,
                "occurred_at": event.occurred_at.isoformat(),
                "visible_events": matrix["visible_events"],
                "annotated": ann is not None,
                "memory_impacted": memory_impacted,
                "b3_decision": b3_m["final_decision"],
                "b3_calls": b3_m["agent_calls"],
                "fixed_calls": a3_m["agent_calls"],
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
                    "recall_count": 0,
                    "false_pass_num": 0,
                    "false_pass_den": 0,
                    "over_defer_num": 0,
                    "over_defer_den": 0,
                    "correct_count": 0,
                    "confusion_matrix": {
                        gold: {pred: 0 for pred in PRED_CLASSES} for gold in THREE_CLASSES
                    },
                    "mf_tp": 0,
                    "mf_fp": 0,
                    "mf_fn": 0,
                    "mf_scenarios": 0,
                })
                bucket["total_calls"] += m["agent_calls"]
                bucket["total_rounds"] += m["discussion_rounds"]
                dec = m["final_decision"] or "NO_OUTPUT"
                bucket["decisions"][dec] = bucket["decisions"].get(dec, 0) + 1
                if m["pre_gate_decision"] == "READY_FOR_REVIEW" and m["final_decision"] in {
                    "NEED_MORE_INFORMATION", "DEFER_DECISION",
                }:
                    bucket["gate_interceptions"] += 1

                selected_agents = set(m["selected_agents"])
                required_agents = set(ann["required_agents"]) if ann is not None else None
                role_hits = len(selected_agents & required_agents) if required_agents is not None else None
                if ann is not None:
                    bucket["annotated_count"] += 1
                    if required_agents:
                        bucket["recall_count"] += 1
                        bucket["recall_sum"] += role_hits / len(required_agents)
                    exp_dec = ann["expected_decision"]
                    pred_key = m["final_decision"] or "NO_OUTPUT"
                    if exp_dec in bucket["confusion_matrix"] and pred_key in bucket["confusion_matrix"][exp_dec]:
                        bucket["confusion_matrix"][exp_dec][pred_key] += 1
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

                    # Missing-field Precision/Recall/F1 against annotated missing_fields
                    gold_missing = set(ann.get("missing_fields") or [])
                    pred_missing = (
                        trigger_only_missing if mid == "A1"
                        else semantic_missing if mid == "A2"
                        else frozen_missing
                    )
                    if gold_missing or pred_missing:
                        bucket["mf_scenarios"] += 1
                        bucket["mf_tp"] += len(pred_missing & gold_missing)
                        bucket["mf_fp"] += len(pred_missing - gold_missing)
                        bucket["mf_fn"] += len(gold_missing - pred_missing)

                    # Error attribution record for discrepancies or missed specialists
                    err_types: list[str] = []
                    missed_agents = sorted(required_agents - selected_agents) if required_agents else []
                    if m["final_decision"] is None:
                        err_types.append("no_output")
                    elif exp_dec in {"NEED_MORE_INFORMATION", "DEFER_DECISION"} and m["final_decision"] == "READY_FOR_REVIEW":
                        err_types.append("false_pass")
                    elif exp_dec == "READY_FOR_REVIEW" and m["final_decision"] in {"NEED_MORE_INFORMATION", "DEFER_DECISION"}:
                        err_types.append("over_deferral")
                    elif m["final_decision"] != exp_dec:
                        err_types.append("decision_mismatch")
                    if missed_agents:
                        err_types.append("missed_specialist")
                    if err_types:
                        error_rows.append({
                            "scenario_id": scenario_id,
                            "case_family_id": family_id,
                            "trigger_event_type": event.event_type,
                            "method_id": mid,
                            "error_types": err_types,
                            "expected_decision": exp_dec,
                            "predicted_decision": m["final_decision"],
                            "required_agents": sorted(required_agents) if required_agents else [],
                            "selected_agents": sorted(selected_agents),
                            "missed_agents": missed_agents,
                            "missing_count": m["missing_count"],
                            "unresolved_conflicts": m["unresolved_conflicts"],
                            "root_cause_hint": _error_root_cause(err_types, m, missed_agents),
                        })

                scenario_rows.append({
                    "scenario_id": scenario_id,
                    "case_family_id": family_id,
                    "case_id": case.case_id,
                    "case_version": case.version,
                    "trigger_event_id": event.event_id,
                    "trigger_event_type": event.event_type,
                    "visible_events": matrix["visible_events"],
                    "method_id": mid,
                    "category": m["category"],
                    "input_case_version": m["input_case_version"],
                    "input_trigger_event_id": m["input_trigger_event_id"],
                    "method_visible_events": m["visible_events"],
                    "trajectory_id": m["trajectory_id"],
                    "agent_calls": m["agent_calls"],
                    "discussion_rounds": m["discussion_rounds"],
                    "pre_gate_decision": m["pre_gate_decision"],
                    "final_decision": m["final_decision"],
                    "missing_count": m["missing_count"],
                    "unresolved_conflicts": m["unresolved_conflicts"],
                    "expected_decision": ann["expected_decision"] if ann else None,
                    "selected_agents": sorted(selected_agents),
                    "required_agents": sorted(required_agents) if required_agents is not None else None,
                    "required_agent_count": len(required_agents) if required_agents is not None else None,
                    "required_agent_hits": role_hits,
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
        mf_tp, mf_fp, mf_fn = b["mf_tp"], b["mf_fp"], b["mf_fn"]
        mf_prec = round(mf_tp / (mf_tp + mf_fp), 4) if (mf_tp + mf_fp) > 0 else None
        mf_rec = round(mf_tp / (mf_tp + mf_fn), 4) if (mf_tp + mf_fn) > 0 else None
        mf_f1 = (
            round(2 * mf_tp / (2 * mf_tp + mf_fp + mf_fn), 4)
            if (2 * mf_tp + mf_fp + mf_fn) > 0 else None
        )
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
            "specialist_recall": round(b["recall_sum"] / b["recall_count"], 4) if b["recall_count"] else None,
            "specialist_recall_scenarios": b["recall_count"],
            "false_pass_count": b["false_pass_num"],
            "false_pass_denominator": b["false_pass_den"],
            "false_pass_rate": round(b["false_pass_num"] / b["false_pass_den"], 4) if b["false_pass_den"] > 0 else None,
            "over_deferral_count": b["over_defer_num"],
            "over_deferral_denominator": b["over_defer_den"],
            "over_deferral_rate": round(b["over_defer_num"] / b["over_defer_den"], 4) if b["over_defer_den"] > 0 else None,
            "correct_count": b["correct_count"],
            "accuracy": round(b["correct_count"] / ann_n, 4) if ann_n > 0 else None,
            "macro_f1": _compute_macro_f1(b["confusion_matrix"]) if ann_n > 0 else None,
            "confusion_matrix": b["confusion_matrix"] if ann_n > 0 else None,
            "missing_field_precision": mf_prec if ann_n > 0 else None,
            "missing_field_recall": mf_rec if ann_n > 0 else None,
            "missing_field_f1": mf_f1 if ann_n > 0 else None,
        })

    return {
        "protocol_version": "mdt-library-eval-v2",
        "execution_mode": "mock",
        "trigger_scope": trigger_scope,
        "family_count": len(families_seen),
        "scenario_count": len(scenarios_meta),
        "annotated_scenario_count": annotated_scenarios,
        "memory_impact_scenarios": memory_impact_count,
        "methods": method_summary,
        "scenarios": scenarios_meta,
        "paired_statistics": _build_paired_statistics(paired_records),
        "error_analysis": error_rows,
        "error_analysis_csv": _build_error_analysis_csv(error_rows),
        "latex_table": _build_latex_table(method_summary, annotated_scenarios),
        "scores_csv": _build_scores_csv(scenario_rows),
    }
