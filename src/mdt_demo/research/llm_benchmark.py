"""G01 real-LLM smoke compatibility suite and paired LLM ablation engine (Plan G01, G04, §6.2–§6.3)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import json
import time
from typing import Literal

from pydantic import ValidationError

from .engine import (
    WorkflowError,
    _review_input,
    _verified_references,
    execute,
    freeze_context,
    source_conflicts,
)
from .provider import PROMPT_VERSION, RunLLM, SYSTEM_PROMPT
from .provider_config import LLMConfigInput, ProviderError, resolve_addresses
from .schemas import AgentOutput, ModelInfo, ResearchCase, RunRequest
from .seeds import seed_cases
from .temporal_audit import audit_temporal_boundary

G01_SMOKE_SCENARIOS: tuple[tuple[str, str, str], ...] = (
    ("LUNG-SYN-001", "E003", "资料齐备路径（肿瘤+病理）"),
    ("LUNG-SYN-001", "E002", "关键资料缺失路径（肿瘤+影像）"),
    ("LUNG-SYN-003", "E004", "同日来源矛盾暂缓路径（全四科）"),
)


class _GeneralReviewOutput(AgentOutput):
    agent_id: Literal["general_reviewer"]


def _plurality(opinions: list[dict]) -> str | None:
    counts = Counter(op["decision"] for op in opinions).most_common(2)
    if not counts:
        return None
    if len(counts) == 2 and counts[0][1] == counts[1][1]:
        return "DEFER_DECISION"
    return counts[0][0]


def _sanitized_config(config: LLMConfigInput, response_format_mode: str) -> dict:
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "timeout_seconds": config.timeout_seconds,
        "temperature": config.temperature,
        "max_output_tokens": config.max_output_tokens,
        "prompt_version": PROMPT_VERSION,
        "response_format_mode": response_format_mode,
    }


def _model_context_matches_source(source: ResearchCase, trigger_id: str, context: dict,
                                  opinion: dict | None = None) -> bool:
    """Audit the evidence actually passed to the provider, including peer citations."""
    peers = list(context["peer_opinions"])
    if context["prior_opinion"] is not None:
        peers.append(context["prior_opinion"])
    audit = audit_temporal_boundary(source, {
        "trigger_event_id": trigger_id,
        "case_snapshot": {
            "case_id": context["case_id"], "version": context["case_version"],
            "current_question": context["current_question"], "timeline": context["events"],
            "unplaced_records": context.get("unplaced_records", []),
        },
        "evidence_registry": context["evidence_registry"],
        "initial_opinions": peers, "final_opinions": [opinion] if opinion is not None else [],
        "discussion_records": [],
    })
    if not audit["passed"]:
        return False
    # Compare the standalone trigger and derived facts too: they are serialized
    # independently of the checked event list in the provider's request.
    if json.dumps(context["trigger_event"], sort_keys=True) != json.dumps(context["events"][-1], sort_keys=True):
        return False
    refs = context["evidence_registry"]
    allowed_values = {(ref["fact_key"], type(ref["value"]), ref["value"]) for ref in refs}
    allowed_ids = {ref["evidence_id"] for ref in refs}
    return (all((key, type(value), value) in allowed_values for key, value in context["current_facts"].items())
            and set(context["required_evidence_ids"]) <= allowed_ids
            and all(set(conflict["evidence_ids"]) <= allowed_ids for conflict in context["conflicts"]))


def _single_llm_b0(source: ResearchCase, frozen: ResearchCase, trigger_id: str, llm: RunLLM) -> dict:
    """Execute one non-specialist B0 LLM call over the exact shared frozen input."""
    started = time.monotonic()
    role = "general_reviewer"
    context = _review_input(frozen)
    conflicts = source_conflicts(frozen, [])
    context.update(
        agent_id=role, phase="initial", run_id="B0_llm",
        prior_opinion=None, peer_opinions=[], conflicts=conflicts,
    )
    registry = {item["evidence_id"]: item for item in context["evidence_registry"]}

    def validate(raw):
        output = _GeneralReviewOutput.model_validate(raw)
        try:
            refs = _verified_references(output, role, context["evidence_registry"])
        except WorkflowError as exc:
            raise ValueError("invalid role or evidence") from exc
        return {**output.model_dump(mode="json"), "evidence_refs": refs}

    opinion = None
    error_code = None
    try:
        result, metadata = llm._request(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, allow_nan=False)},
            ],
            _GeneralReviewOutput.model_json_schema(),
            "mdt_general_review_opinion",
            validate,
            track_telemetry=True,
            registry=registry,
        )
        ModelInfo.model_validate(metadata)
        opinion = result
    except ProviderError as exc:
        error_code = exc.code
    except (ValidationError, ValueError):
        error_code = "LLM_INVALID_OUTPUT"

    wall_ms = round((time.monotonic() - started) * 1000, 2)
    decision = opinion["decision"] if opinion else None
    return {
        "trajectory_id": "B0",
        "input_case_version": frozen.version,
        "input_trigger_event_id": frozen.timeline[-1].event_id,
        "visible_events": len(frozen.timeline),
        "selected_agents": [role],
        "agent_calls": 1,
        "llm_calls": llm.metrics["llm_calls"],
        "retry_count": llm.metrics["retry_count"],
        "prompt_tokens": llm.metrics["prompt_tokens"],
        "completion_tokens": llm.metrics["completion_tokens"],
        "discussion_rounds": 0,
        "valid_opinions": int(opinion is not None),
        "failed_calls": int(opinion is None),
        "error_code": error_code,
        "status": "completed" if opinion is not None else "failed",
        "pre_gate_decision": decision,
        "final_decision": decision,
        "missing_count": len(context["missing_information"]),
        "unresolved_conflicts": len(conflicts),
        "wall_clock_ms": wall_ms,
        "temporal_audit_passed": _model_context_matches_source(source, trigger_id, context, opinion),
        "validation_telemetry": llm.validation_summary(),
    }


def _llm_trajectory(
    original_case: ResearchCase,
    run_case: ResearchCase,
    trigger_id: str,
    method_id: str,
    llm: RunLLM,
    *,
    routing: str = "event",
    discussion: bool = True,
) -> dict:
    started = time.monotonic()
    request = RunRequest(
        case_id=run_case.case_id,
        case_version=run_case.version,
        trigger_event_id=trigger_id,
        mode="llm",
        routing_mode=routing,
    )
    audit_source = original_case
    if method_id == "A1":
        # Reconstruct this arm's intended input directly from the full source.
        trigger = next(event for event in original_case.timeline if event.event_id == trigger_id)
        audit_source = original_case.model_copy(update={"timeline": [trigger]})
    input_checks = []

    def call_model(context):
        input_checks.append(_model_context_matches_source(audit_source, trigger_id, context))
        return llm(context)

    call_model.metrics = llm.metrics
    report = execute(run_case, request, f"llm_{method_id}", lambda *args: None, lambda: False,
                     llm=call_model, allow_discussion=discussion)
    wall_ms = round((time.monotonic() - started) * 1000, 2)
    audit = audit_temporal_boundary(audit_source, report)
    successful_calls = len(report["initial_opinions"]) + sum(
        rec["after"] is not None for rec in report["discussion_records"]
    )
    return {
        "trajectory_id": method_id,
        "input_case_version": run_case.version,
        "input_trigger_event_id": trigger_id,
        "visible_events": len(report["case_snapshot"]["timeline"]),
        "selected_agents": report["routing"]["selected_agents"],
        "agent_calls": report["metrics"]["agent_calls"],
        "llm_calls": report["metrics"]["llm_calls"],
        "retry_count": report["metrics"]["retry_count"],
        "prompt_tokens": report["metrics"]["prompt_tokens"],
        "completion_tokens": report["metrics"]["completion_tokens"],
        "discussion_rounds": report["discussion_rounds"],
        "valid_opinions": len(report["final_opinions"]),
        "failed_calls": report["metrics"]["agent_calls"] - successful_calls,
        "status": report["status"],
        "pre_gate_decision": _plurality(report["final_opinions"]),
        "final_decision": report["final_decision"],
        "missing_count": len(report["safety"]["missing_information"]),
        "unresolved_conflicts": len(report["unresolved_conflicts"]),
        "wall_clock_ms": wall_ms,
        "temporal_audit_passed": audit["passed"] and bool(input_checks) and all(input_checks),
        "validation_telemetry": llm.validation_summary(),
    }


def run_g01_smoke_suite(
    config: LLMConfigInput,
    *,
    transport=None,
    resolver=resolve_addresses,
    response_format_mode: str = "json_schema",
    sleep_seconds: float = 0.0,
) -> dict:
    """Execute the Plan G01 / S1 end-to-end LLM compatibility & smoke validation suite."""
    sanitized = _sanitized_config(config, response_format_mode)

    # 1. Connection test (no patient data)
    conn_llm = RunLLM(config, transport=transport, resolver=resolver, response_format_mode=response_format_mode)
    t0 = time.monotonic()
    connection = {"ok": False, "error_code": None, "message": "", "wall_clock_ms": 0.0}
    try:
        res = conn_llm.test()
        connection.update(ok=True, message=res["message"], wall_clock_ms=round((time.monotonic() - t0) * 1000, 2))
    except ProviderError as exc:
        connection.update(ok=False, error_code=exc.code, message=exc.message,
                          wall_clock_ms=round((time.monotonic() - t0) * 1000, 2))

    cases_by_id = {case.case_id: case for case in seed_cases()}
    runs: list[dict] = []
    agg_telemetry = {
        "first_attempt_calls": 0,
        "first_attempt_valid": 0,
        "first_attempt_schema_failures": 0,
        "first_attempt_evidence_failures": 0,
        "first_attempt_http_or_refusal_failures": 0,
        "first_attempt_candidate_citations": 0,
        "first_attempt_valid_citations": 0,
        "first_attempt_candidate_claims": 0,
        "first_attempt_valid_claims": 0,
        "retry_recovered": 0,
        "final_valid_calls": 0,
        "final_failed_calls": 0,
    }
    total_prompt = 0
    total_completion = 0
    usage_complete = True

    for case_id, trigger_id, description in G01_SMOKE_SCENARIOS:
        if sleep_seconds > 0 and runs:
            time.sleep(sleep_seconds)
        case = cases_by_id[case_id]
        run_llm = RunLLM(config, transport=transport, resolver=resolver, response_format_mode=response_format_mode)
        request = RunRequest(case_id=case_id, case_version=1, trigger_event_id=trigger_id,
                             mode="llm", routing_mode="event")
        started = time.monotonic()
        report = execute(case, request, f"g01_{case_id}_{trigger_id}", lambda *args: None, lambda: False, llm=run_llm)
        wall_ms = round((time.monotonic() - started) * 1000, 2)
        audit = audit_temporal_boundary(case, report)
        telemetry = run_llm.validation_summary()
        for k in agg_telemetry:
            agg_telemetry[k] += telemetry[k]
        m = report["metrics"]
        if m["prompt_tokens"] is None or m["completion_tokens"] is None:
            usage_complete = False
        else:
            total_prompt += m["prompt_tokens"]
            total_completion += m["completion_tokens"]

        runs.append({
            "scenario_id": f"{case_id}:v1:{trigger_id}",
            "description": description,
            "status": report["status"],
            "final_decision": report["final_decision"],
            "selected_agents": report["routing"]["selected_agents"],
            "valid_opinions": len(report["final_opinions"]),
            "discussion_rounds": report["discussion_rounds"],
            "conflicts_detected": len(report["conflicts"]),
            "unresolved_conflicts": len(report["unresolved_conflicts"]),
            "missing_information": report["safety"]["missing_information"],
            "metrics": {**m, "wall_clock_ms": wall_ms},
            "validation_telemetry": telemetry,
            "temporal_audit": {
                "passed": audit["passed"],
                "leaked_count": audit["leaked_count"],
                "same_day_events_on_cutoff": audit["same_day_events_on_cutoff"],
            },
            "warnings": report["safety"]["warnings"],
        })

    all_completed = all(item["status"] == "completed" for item in runs)
    all_temporal_ok = all(item["temporal_audit"]["passed"] for item in runs)
    calls = agg_telemetry["first_attempt_calls"]
    cites = agg_telemetry["first_attempt_candidate_citations"]

    return {
        "protocol_version": "g01-llm-smoke-v1",
        "model_config": sanitized,
        "connection_test": connection,
        "compatibility": {
            "connection_passed": connection["ok"],
            "all_scenarios_completed": all_completed,
            "all_temporal_audits_passed": all_temporal_ok,
            "usage_reported_complete": usage_complete,
            "total_prompt_tokens": total_prompt if usage_complete else None,
            "total_completion_tokens": total_completion if usage_complete else None,
            "first_attempt_valid_rate": round(agg_telemetry["first_attempt_valid"] / calls, 4) if calls else None,
            "first_attempt_citation_valid_rate": round(agg_telemetry["first_attempt_valid_citations"] / cites, 4) if cites else None,
            "validation_totals": agg_telemetry,
        },
        "scenarios": runs,
    }


def evaluate_llm_ablation_matrix(
    case: ResearchCase,
    trigger_event_id: str,
    llm_factory: Callable[[], RunLLM],
    *,
    sleep_seconds: float = 0.0,
) -> dict:
    """Run paired B0–B3 and A1/A3/A4 ablations over a frozen cutoff using real/injected LLM calls."""
    frozen = freeze_context(case, trigger_event_id)

    def pause():
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    b0 = _single_llm_b0(case, frozen, trigger_event_id, llm_factory())
    pause()
    b1 = _llm_trajectory(case, frozen, trigger_event_id, "B1", llm_factory(), routing="fixed", discussion=False)
    pause()
    shared = _llm_trajectory(case, frozen, trigger_event_id, "B3", llm_factory(), routing="event", discussion=True)
    pause()
    trigger_only = frozen.model_copy(update={"timeline": [frozen.timeline[-1]]})
    a1 = _llm_trajectory(case, trigger_only, trigger_event_id, "A1", llm_factory(), routing="event", discussion=True)
    pause()
    a3 = _llm_trajectory(case, frozen, trigger_event_id, "A3", llm_factory(), routing="fixed", discussion=True)
    pause()
    a4 = _llm_trajectory(case, frozen, trigger_event_id, "A4", llm_factory(), routing="event", discussion=False)

    def row(mid: str, name: str, category: str, strategy: str, trace: dict, note: str, *, gate: bool) -> dict:
        return {
            **trace,
            "method_id": mid,
            "name": f"{mid} · {name}",
            "category": category,
            "routing_strategy": strategy,
            "key_finding": note,
            "gate_applied": gate,
            "final_decision": trace["final_decision"] if gate else trace["pre_gate_decision"],
        }

    methods = [
        row("B0", "单审阅者", "基线对照", "通用审阅", b0, "通用单模型独立审阅共同冻结输入。", gate=False),
        row("B1", "固定全员无协商", "基线对照", "固定四专科", b1, "固定四科独立初审，相对多数聚合（平票暂缓）。", gate=False),
        row("B2", "事件路由与定向协商", "基线对照", "事件路由", shared, "与 B3 共享真实模型轨迹，记录门控前聚合结论。", gate=False),
        row("B3", "完整工作流", "基线对照", "事件路由", shared, "事件路由 + 有界定向协商 + 证据与资料安全门控。", gate=True),
        row("A1", "仅当前事件", "单因素消融", "事件路由", a1, f"相对 B3 移除 {len(frozen.timeline) - 1} 条前序事件。", gate=True),
        row("A3", "固定全员", "单因素消融", "固定四专科", a3, "相对 B3 仅改为固定全员路由，保留协商与门控。", gate=True),
        row("A4", "关闭协商", "单因素消融", "事件路由", a4, "相对 B3 仅关闭讨论轮次，保留冲突检测与门控。", gate=True),
    ]
    fixed_calls = a3["agent_calls"]
    routed_calls = shared["agent_calls"]
    return {
        "protocol_version": "llm-matrix-v1",
        "execution_mode": "llm",
        "case_id": case.case_id,
        "case_version": case.version,
        "trigger_event_id": trigger_event_id,
        "visible_events": len(frozen.timeline),
        "methods": methods,
        "fixed_total_calls": fixed_calls,
        "routed_total_calls": routed_calls,
        "call_saving_pct": round(100 * (fixed_calls - routed_calls) / fixed_calls) if fixed_calls else 0,
    }
