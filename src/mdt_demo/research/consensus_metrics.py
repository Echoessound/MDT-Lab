"""Core longitudinal MDT algorithms: risk-utility routing, deliberation entropy/consensus, and trajectory dynamics."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
import math

from .engine import (
    REQUIRED,
    ROUTES,
    current_fact_records,
    current_fact_values,
    execute,
    freeze_context,
    route_case,
    source_conflicts,
)
from .schemas import ROLES, ResearchCase, RunRequest

UTILITY_THRESHOLD = 0.50
ADAPTIVE_ROUTER_VERSION = "adaptive-utility-router-v1"
_CONFIDENCE_WEIGHTS = {"low": 0.6, "medium": 0.85, "high": 1.0}

_DOMAIN_CONFLICT_KEYS: dict[str, set[str]] = {
    "radiology": {"imaging_complete", "progression_confirmed"},
    "pathology": {
        "pathology_confirmed", "histology", "molecular_complete",
        "egfr_status", "kras_status", "alk_status",
        "pathological_t", "pathological_n", "pathological_m",
    },
    "surgery": {"procedure_record_complete", "pathological_t", "pathological_n", "pathological_m"},
}


def compute_specialist_utilities(frozen: ResearchCase) -> dict:
    """Score specialist participation utility strictly over a temporally frozen case."""
    trigger = frozen.timeline[-1]
    latest = current_fact_values(current_fact_records(frozen))
    required = REQUIRED[trigger.event_type]
    missing_req = [key for key in required if latest.get(key) is not True]
    conflicts = source_conflicts(frozen, list(ROLES))
    conflict_keys = {
        item["conflict_id"].removeprefix("source_")
        for item in conflicts
        if item["conflict_id"].startswith("source_")
    }

    imaging_events = [
        ev for ev in frozen.timeline
        if ev.event_type == "imaging" or ev.facts.get("imaging_complete") is True
    ]
    imaging_staleness_days = (
        (trigger.occurred_at - imaging_events[-1].occurred_at).days if imaging_events else None
    )
    span_days = (trigger.occurred_at - frozen.timeline[0].occurred_at).days
    has_procedure = any(ev.event_type == "procedure" for ev in frozen.timeline)
    has_molecular = any(
        ev.event_type == "molecular_test" or "molecular_complete" in ev.facts
        for ev in frozen.timeline
    )
    base_roles = set(ROUTES[trigger.event_type])

    per_role: dict[str, dict] = {}
    for role in ROLES:
        base = 0.65 if role in base_roles else 0.10
        signals: list[str] = []
        if role in base_roles:
            signals.append(f"事件类型 {trigger.event_type} 基础命中")

        deficit = 0.0
        if role == "radiology":
            if (
                "imaging_complete" in missing_req
                or latest.get("imaging_complete") is False
                or "progression_confirmed" in missing_req
                or latest.get("progression_confirmed") is False
            ):
                deficit = 0.45
                signals.append("影像或进展状态存在缺失/未齐备标记")
        elif role == "pathology":
            if (
                "pathology_confirmed" in missing_req
                or latest.get("pathology_confirmed") is False
                or "molecular_complete" in missing_req
                or latest.get("molecular_complete") is False
                or ("histology" in latest and latest.get("pathology_confirmed") is not True)
            ):
                deficit = 0.45
                signals.append("病理或分子检测记录存在缺口/未确认")
        elif role == "surgery":
            if (
                "procedure_record_complete" in missing_req
                or latest.get("procedure_record_complete") is False
                or (has_procedure and trigger.event_type in {"follow_up", "progression", "recurrence", "imaging"})
            ):
                deficit = 0.45
                signals.append("存在围手术期操作缺口或术后随访/复发复核")
        elif role == "oncology":
            oncology_keys = {"treatment_record_complete", "toxicity_assessed", "follow_up_complete", "observation_reviewed"}
            if (
                any(k in missing_req or latest.get(k) is False for k in oncology_keys)
                or len(missing_req) >= 2
            ):
                deficit = 0.45
                signals.append("综合治疗/随访指标缺口或多项必需资料未齐备")

        conflict_boost = 0.0
        if role == "oncology":
            if conflicts:
                conflict_boost = 0.50
                signals.append("存在未消解同日来源矛盾，需统筹复核")
        elif conflict_keys & _DOMAIN_CONFLICT_KEYS.get(role, set()):
            conflict_boost = 0.50
            signals.append("专科域关键事实存在同日矛盾")

        staleness = 0.0
        if role == "radiology" and trigger.event_type in {"follow_up", "treatment", "medication", "progression", "recurrence"}:
            if imaging_staleness_days is None or imaging_staleness_days > 60:
                staleness = 0.45
                note = f"距离最近影像评估已逾 {imaging_staleness_days} 天" if imaging_staleness_days is not None else "此前尚无有效影像归档"
                signals.append(note)
        elif role == "pathology" and trigger.event_type in {"treatment", "medication", "progression", "recurrence"}:
            if not has_molecular and span_days > 60:
                staleness = 0.45
                signals.append(f"病程已跨度 {span_days} 天且尚无分子检测记录")

        score = round(min(1.0, base + deficit + conflict_boost + staleness), 2)
        selected = score >= UTILITY_THRESHOLD
        per_role[role] = {
            "agent_id": role,
            "selected": selected,
            "utility_score": score,
            "components": {
                "base": round(base, 2),
                "deficit": round(deficit, 2),
                "conflict": round(conflict_boost, 2),
                "staleness": round(staleness, 2),
            },
            "signals": signals,
            "description": (
                f"效用 {score:.2f} ≥ {UTILITY_THRESHOLD:.2f}（{'；'.join(signals) if signals else '达调度阈值'}）。"
                if selected
                else f"效用 {score:.2f} < {UTILITY_THRESHOLD:.2f}，当前截点风险与资料缺口均未触发该专科。"
            ),
        }

    selected_agents = [role for role in ROLES if per_role[role]["selected"]]
    if not selected_agents:
        selected_agents = ["oncology"]
        per_role["oncology"]["selected"] = True
        per_role["oncology"]["description"] = "保底调度肿瘤内科统筹审阅。"

    return {
        "strategy_version": ADAPTIVE_ROUTER_VERSION,
        "threshold": UTILITY_THRESHOLD,
        "trigger_event_id": trigger.event_id,
        "imaging_staleness_days": imaging_staleness_days,
        "selected_agents": selected_agents,
        "skipped_agents": [role for role in ROLES if role not in selected_agents],
        "utilities": [per_role[role] for role in ROLES],
    }


def _normalized_shannon_entropy(opinions: list[dict]) -> float:
    if len(opinions) <= 1:
        return 0.0
    counts = Counter(item["decision"] for item in opinions)
    total = len(opinions)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log(p)
    return round(min(1.0, max(0.0, entropy / math.log(3))), 4)


def _pairwise_evidence_jaccard(opinions: list[dict]) -> tuple[float | None, int]:
    scores: list[float] = []
    for left, right in combinations(opinions, 2):
        s1 = set(left.get("evidence_ids", []))
        s2 = set(right.get("evidence_ids", []))
        if s1 or s2:
            scores.append(len(s1 & s2) / len(s1 | s2))
    return (round(sum(scores) / len(scores), 4) if scores else None), len(scores)


def _claim_comparisons(opinions: list[dict]) -> tuple[int, int]:
    comparable = 0
    matched = 0
    for left, right in combinations(opinions, 2):
        right_by_key: dict[str, list] = {}
        for claim in right.get("claims", []):
            right_by_key.setdefault(claim["fact_key"], []).append(claim["value"])
        for claim in left.get("claims", []):
            key = claim["fact_key"]
            if key not in right_by_key:
                continue
            for rval in right_by_key[key]:
                comparable += 1
                if type(claim["value"]) is type(rval) and claim["value"] == rval:
                    matched += 1
    return matched, comparable


def compute_run_consensus_metrics(report: dict) -> dict:
    """Quantify deliberation entropy reduction, inter-agent agreement, and gated consensus score."""
    selected = report["routing"]["selected_agents"]
    initial = report["initial_opinions"]
    final = report["final_opinions"]
    unresolved = report["unresolved_conflicts"]

    initial_entropy = _normalized_shannon_entropy(initial)
    final_entropy = _normalized_shannon_entropy(final)
    coverage_ratio = round(len(final) / max(1, len(selected)), 4)

    total_weight = sum(_CONFIDENCE_WEIGHTS.get(op.get("confidence", "medium"), 0.85) for op in final)
    supporting_weight = sum(
        _CONFIDENCE_WEIGHTS.get(op.get("confidence", "medium"), 0.85)
        for op in final
        if op["decision"] == report["final_decision"]
    )
    weighted_support = (supporting_weight / total_weight) if total_weight > 0 else 0.0
    safety_veto_applied = bool(unresolved) or coverage_ratio < 1.0
    consensus_score = 0.0 if safety_veto_applied else round(weighted_support * coverage_ratio, 4)

    unique_cited = {ev_id for op in final for ev_id in op.get("evidence_ids", [])}
    evidence_util = round(len(unique_cited) / max(1, len(report["evidence_registry"])), 4)
    jaccard, evidence_pairs = _pairwise_evidence_jaccard(final)
    matched, comparable = _claim_comparisons(final)

    return {
        "run_id": report["run_id"],
        "case_id": report["case_id"],
        "case_version": report["case_version"],
        "trigger_event_id": report["trigger_event_id"],
        "routing_mode": report["routing_mode"],
        "initial_entropy": initial_entropy,
        "final_entropy": final_entropy,
        "entropy_reduction": round(initial_entropy - final_entropy, 4),
        "opinions_revised_count": sum(1 for item in report["discussion_records"] if item.get("changed")),
        "converged": (len({op["decision"] for op in final}) == 1 and len(final) == len(selected))
                     if len(final) >= 2 else None,
        "coverage_ratio": coverage_ratio,
        "evidence_jaccard_mean": jaccard,
        "evidence_pair_count": evidence_pairs,
        "claim_agreement_rate": round(matched / comparable, 4) if comparable else None,
        "comparable_claim_pairs": comparable,
        "matched_claim_pairs": matched,
        "unique_cited_evidence_count": len(unique_cited),
        "evidence_utilization_rate": evidence_util,
        "consensus_score": consensus_score,
        "safety_veto_applied": safety_veto_applied,
        "final_decision": report["final_decision"],
    }


def compute_case_longitudinal_dynamics(case: ResearchCase) -> dict:
    """Trace cutoff-by-cutoff decisions, transitions, and routing efficiency across the timeline."""
    checkpoints: list[dict] = []
    sum_event = 0
    sum_adaptive = 0
    sum_fixed = 0
    escalations = 0

    for event in case.timeline:
        frozen = freeze_context(case, event.event_id)
        adaptive_util = compute_specialist_utilities(frozen)
        event_route = route_case(frozen, event.event_id, "event")

        rep_event = execute(
            case,
            RunRequest(case_id=case.case_id, case_version=case.version, trigger_event_id=event.event_id, routing_mode="event"),
            f"dyn_evt_{event.event_id}",
            lambda *args: None,
            lambda: False,
        )
        rep_adaptive = execute(
            case,
            RunRequest(case_id=case.case_id, case_version=case.version, trigger_event_id=event.event_id, routing_mode="adaptive"),
            f"dyn_adp_{event.event_id}",
            lambda *args: None,
            lambda: False,
        )
        rep_fixed = execute(
            case,
            RunRequest(case_id=case.case_id, case_version=case.version, trigger_event_id=event.event_id, routing_mode="fixed"),
            f"dyn_fix_{event.event_id}",
            lambda *args: None,
            lambda: False,
        )

        event_calls = rep_event["metrics"]["agent_calls"]
        adaptive_calls = rep_adaptive["metrics"]["agent_calls"]
        fixed_calls = rep_fixed["metrics"]["agent_calls"]
        sum_event += event_calls
        sum_adaptive += adaptive_calls
        sum_fixed += fixed_calls
        if set(adaptive_util["selected_agents"]) - set(event_route["selected_agents"]):
            escalations += 1

        checkpoints.append({
            "event_id": event.event_id,
            "occurred_at": event.occurred_at.isoformat(),
            "event_type": event.event_type,
            "title": event.title,
            "event_selected_agents": event_route["selected_agents"],
            "adaptive_selected_agents": adaptive_util["selected_agents"],
            "event_calls": event_calls,
            "adaptive_calls": adaptive_calls,
            "fixed_calls": fixed_calls,
            "missing_count": len(rep_event["safety"]["missing_information"]),
            "source_conflict_count": len(source_conflicts(frozen, list(ROLES))),
            "event_decision": rep_event["final_decision"],
            "adaptive_decision": rep_adaptive["final_decision"],
            "imaging_staleness_days": adaptive_util["imaging_staleness_days"],
        })

    first_ready = next((cp["event_id"] for cp in checkpoints if cp["event_decision"] == "READY_FOR_REVIEW"), None)
    transitions = 0
    oscillations = 0
    for prev, curr in zip(checkpoints, checkpoints[1:]):
        if prev["event_decision"] != curr["event_decision"]:
            transitions += 1
            if prev["event_decision"] == "READY_FOR_REVIEW" and curr["event_decision"] in {"NEED_MORE_INFORMATION", "DEFER_DECISION"}:
                oscillations += 1

    return {
        "case_id": case.case_id,
        "case_version": case.version,
        "checkpoint_count": len(checkpoints),
        "first_ready_event_id": first_ready,
        "transition_count": transitions,
        "decision_oscillation_count": oscillations,
        "cumulative_calls": {
            "event": sum_event,
            "adaptive": sum_adaptive,
            "fixed": sum_fixed,
        },
        "event_saving_vs_fixed_pct": round(100 * (sum_fixed - sum_event) / max(1, sum_fixed), 1),
        "adaptive_saving_vs_fixed_pct": round(100 * (sum_fixed - sum_adaptive) / max(1, sum_fixed), 1),
        "adaptive_risk_escalations": escalations,
        "checkpoints": checkpoints,
    }
