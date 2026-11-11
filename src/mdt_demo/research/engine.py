"""Event-routed, bounded research workflow over a frozen synthetic timeline."""

from copy import deepcopy
from itertools import combinations
import json
import time

from pydantic import ValidationError

from .schemas import (
    AgentOutput, Conflict, EvidenceRef, Metrics, ModelInfo, Opinion, Report,
    ResearchCase, ROLES, Routing, RunRequest, Safety,
)

RULE_VERSION = "event-router-v1"
REQUIRED = {
    "diagnosis": ["imaging_complete", "pathology_confirmed"],
    "imaging": ["imaging_complete", "pathology_confirmed"],
    "pathology": ["pathology_confirmed"],
    "molecular_test": ["molecular_complete", "pathology_confirmed"],
    "procedure": ["procedure_record_complete", "pathology_confirmed"],
    "treatment": ["treatment_record_complete", "pathology_confirmed"],
    "medication": ["treatment_record_complete", "pathology_confirmed"],
    "toxicity": ["toxicity_assessed"],
    "follow_up": ["follow_up_complete", "imaging_complete"],
    "progression": ["progression_confirmed", "imaging_complete", "pathology_confirmed"],
    "recurrence": ["progression_confirmed", "imaging_complete", "pathology_confirmed"],
    "observation": ["observation_reviewed"],
}
ROUTES = {
    "diagnosis": list(ROLES), "imaging": ["oncology", "radiology"],
    "pathology": ["oncology", "pathology"], "molecular_test": ["oncology", "pathology"],
    "procedure": ["oncology", "surgery"], "treatment": ["oncology"],
    "medication": ["oncology"], "toxicity": ["oncology"],
    "follow_up": ["oncology", "radiology"], "progression": list(ROLES),
    "recurrence": list(ROLES), "observation": ["oncology"],
}
SAFE_ERRORS = {
    "LLM_AUTHENTICATION_ERROR", "LLM_RATE_LIMIT", "LLM_PROVIDER_ERROR", "LLM_TIMEOUT",
    "LLM_NETWORK_ERROR", "LLM_INVALID_OUTPUT", "LLM_REQUEST_REJECTED", "LLM_REFUSED",
    "LLM_DNS_ERROR", "LLM_PRIVATE_DESTINATION", "LLM_NOT_CONFIGURED",
}


class WorkflowCancelled(Exception):
    pass


class WorkflowError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def freeze_context(case: ResearchCase, trigger_event_id: str) -> ResearchCase:
    case = ResearchCase.model_validate(case.model_dump(mode="json"))
    trigger = next((event for event in case.timeline if event.event_id == trigger_event_id), None)
    if trigger is None:
        raise WorkflowError("event_not_found")
    cutoff = (trigger.occurred_at, trigger.event_id)
    payload = case.model_dump(mode="json")
    payload["timeline"] = [event.model_dump(mode="json") for event in case.timeline
                           if (event.occurred_at, event.event_id) <= cutoff]
    # Retrospective table fields without an availability date must never enter
    # a historical model prompt or its report snapshot.
    payload["unplaced_records"] = []
    return ResearchCase.model_validate(payload)


def route_case(case: ResearchCase, trigger_event_id: str, routing_mode: str = "event") -> dict:
    frozen = freeze_context(case, trigger_event_id)
    trigger = frozen.timeline[-1]
    if routing_mode not in {"event", "fixed"}:
        raise WorkflowError("invalid_routing_mode")
    selected = list(ROLES) if routing_mode == "fixed" else ROUTES[trigger.event_type].copy()
    return Routing(
        strategy_version=RULE_VERSION, trigger_event_id=trigger_event_id,
        selected_agents=selected, skipped_agents=[role for role in ROLES if role not in selected],
        reasons=[{"agent_id": role, "rule_id": "fixed_all" if routing_mode == "fixed" else f"event_{trigger.event_type}",
                  "description": "固定全员对照：调用全部注册专科。" if routing_mode == "fixed" else (
                      f"触发事件为 {trigger.event_type}，命中科研路由规则。" if role in selected
                      else f"本次 {trigger.event_type} 事件未命中该专科规则，跳过调用。"
                  )} for role in ROLES],
    ).model_dump(mode="json")


def evidence_registry(case: ResearchCase) -> list[dict]:
    sources = {source.source_name: source for source in case.provenance}
    return [EvidenceRef(
        evidence_id=f"{event.event_id}:{key}", event_id=event.event_id, fact_key=key, value=value,
        source_name=event.source, source_record_id=event.source_record_id,
        dataset_version=sources[event.source].dataset_version, synthetic=sources[event.source].synthetic,
        artifact_sha256=sources[event.source].artifact_sha256,
        source_record_locator=event.source_record_locator, source_field=event.source_fields.get(key),
        quote_or_fact=f"{key} = {json.dumps(value, ensure_ascii=False, allow_nan=False)}",
    ).model_dump(mode="json") for event in case.timeline for key, value in event.facts.items()]


def _current_facts(case, registry):
    latest = {}
    for item in registry:
        latest[item["fact_key"]] = item
    return latest


def source_conflicts(case: ResearchCase, selected: list[str]) -> list[dict]:
    """Only opposing structured facts at the latest date conflict; later updates supersede history."""
    material_keys = set(key for values in REQUIRED.values() for key in values) | {"histology"}
    grouped = {}
    for event in case.timeline:
        for key, value in event.facts.items():
            if key not in material_keys or value is None:
                continue
            grouped.setdefault(key, []).append((event, value))
    result = []
    for key, records in grouped.items():
        last_date = max(event.occurred_at for event, _ in records)
        current = [(event, value) for event, value in records if event.occurred_at == last_date]
        superseded = {event.facts.get("supersedes_event_id") for event, _ in current}
        current = [(event, value) for event, value in current if event.event_id not in superseded]
        distinct = {(type(value).__name__, json.dumps(value, ensure_ascii=False)) for _, value in current}
        if len(distinct) > 1:
            result.append({"conflict_id": f"source_{key}", "dimension": "source_fact_conflict",
                           "agent_ids": selected, "description": f"同日来源对 {key} 有相反事实，尚无明确替代记录。",
                           "evidence_ids": [f"{event.event_id}:{key}" for event, _ in current]})
    return result


def detect_conflicts(opinions: list[dict], source: list[dict]) -> list[dict]:
    result = deepcopy(source)
    if len({item["decision"] for item in opinions}) > 1:
        result.append({"conflict_id": "decision_difference", "dimension": "information_sufficiency",
                       "agent_ids": [item["agent_id"] for item in opinions],
                       "description": "相关角色对资料是否充分的流程标签不一致。", "evidence_ids": []})
    seen = set()
    for left, right in combinations(opinions, 2):
        for a in left["claims"]:
            for b in right["claims"]:
                if a["fact_key"] == b["fact_key"] and (type(a["value"]) is not type(b["value"]) or a["value"] != b["value"]):
                    key = (a["fact_key"], left["agent_id"], right["agent_id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append({"conflict_id": f"claim_{len(result)}", "dimension": "structured_fact_difference",
                                   "agent_ids": [left["agent_id"], right["agent_id"]],
                                   "description": f"角色引用的 {a['fact_key']} 事实取值不同，需要核对时间与来源。",
                                   "evidence_ids": [a["evidence_id"], b["evidence_id"]]})
    return [Conflict.model_validate(item).model_dump(mode="json") for item in result]


def validate_output(raw: dict, role: str, registry: list[dict], opinion_id: str) -> dict:
    payload = deepcopy(raw)
    metadata = payload.pop("model_info", None)
    output = AgentOutput.model_validate(payload)
    index = {item["evidence_id"]: item for item in registry}
    if output.agent_id != role or not set(output.evidence_ids) <= set(index):
        raise WorkflowError("invalid_evidence")
    for claim in output.claims:
        item = index[claim.evidence_id]
        if claim.fact_key != item["fact_key"] or type(claim.value) is not type(item["value"]) or claim.value != item["value"]:
            raise WorkflowError("invalid_evidence")
    return Opinion(**output.model_dump(), opinion_id=opinion_id,
                   evidence_refs=[index[key] for key in output.evidence_ids],
                   model_info=ModelInfo.model_validate(metadata)).model_dump(mode="json")


def _mock(context: dict, scenario: str, designated: str, selected: list[str]) -> dict:
    role, missing = context["agent_id"], context["missing_information"]
    if scenario == "partial_failure" and role == designated:
        raise WorkflowError("simulated_agent_failure")
    lookup = {item["evidence_id"]: item for item in context["evidence_registry"]}
    latest = {}
    for item in lookup.values():
        latest[item["fact_key"]] = item
    chosen = [latest[key] for key in context["required_fields"] if key in latest]
    if not chosen:
        chosen = [list(lookup.values())[-1]]
    decision = "NEED_MORE_INFORMATION" if missing else "READY_FOR_REVIEW"
    if any(item["dimension"] == "source_fact_conflict" for item in context["conflicts"]):
        decision = "DEFER_DECISION"
    # This disagreement is an explicit scripted test condition, not medical inference.
    if role == designated and len(selected) > 1:
        if scenario == "persistent_disagreement":
            decision = "READY_FOR_REVIEW" if decision != "READY_FOR_REVIEW" else "NEED_MORE_INFORMATION"
        elif scenario == "standard" and missing and context["phase"] == "initial":
            decision = "READY_FOR_REVIEW"
    ids = [item["evidence_id"] for item in chosen]
    claims = [{"fact_key": item["fact_key"], "value": item["value"], "evidence_id": item["evidence_id"]} for item in chosen]
    if scenario == "invalid_evidence" and role == designated:
        ids = ["UNKNOWN:imaging_complete"]
        claims = [{"fact_key": "imaging_complete", "value": True, "evidence_id": ids[0]}]
    return {"agent_id": role, "decision": decision,
            "summary": f"预设 Mock 资料审阅脚本：依据冻结病例中的 {len(chosen)} 项结构化事实核对记录。" + (
                "仍存在关键资料缺口。" if missing else "科研规则所需记录已提供。"),
            "evidence_ids": ids, "claims": claims,
            "missing_information": missing if decision != "READY_FOR_REVIEW" else [], "confidence": "medium",
            "model_info": {"provider": "mock", "model": "deterministic-research-v1", "prompt_version": "mock-rules-v1", "attempts": 1,
                           "prompt_tokens": None, "completion_tokens": None}}


def execute(case: ResearchCase, request: RunRequest, run_id: str, emit, cancelled, llm=None) -> dict:
    started = time.monotonic()
    if case.case_id != request.case_id or case.version != request.case_version:
        raise WorkflowError("case_version_mismatch")
    if request.mode == "llm" and llm is None:
        raise WorkflowError("llm_not_configured")
    if request.mode == "llm" and request.mock_scenario != "standard":
        raise WorkflowError("mock_scenario_in_llm_mode")
    completed, running = [], []
    nodes = ["case_validation", "routing", "conflict_detection", "safety_gate", "report"]
    metrics = Metrics().model_dump()

    def check():
        if cancelled():
            raise WorkflowCancelled()

    def progress(stage):
        emit("workflow.progress", stage, {"completed_nodes": completed.copy(), "running_nodes": running.copy(),
                                         "pending_nodes": [node for node in nodes if node not in completed + running]})

    def begin(node, stage):
        check()
        running[:] = [node]
        emit("workflow.stage_changed", stage, {"stage": stage})
        progress(stage)
        check()

    def finish(node, stage):
        check()
        if node not in completed:
            completed.append(node)
        running.clear()
        progress(stage)

    begin("case_validation", "INITIALIZING")
    frozen = freeze_context(case, request.trigger_event_id)
    trigger = frozen.timeline[-1]
    finish("case_validation", "INITIALIZING")
    begin("routing", "ROUTING")
    routing = route_case(frozen, request.trigger_event_id, request.routing_mode)
    selected = routing["selected_agents"]
    if request.mock_scenario == "persistent_disagreement" and len(selected) < 2:
        raise WorkflowError("scenario_requires_multiple_agents")
    nodes[2:2] = [f"{role}_review" for role in selected]
    emit("routing.completed", "ROUTING", routing)
    finish("routing", "ROUTING")

    registry = evidence_registry(frozen)
    facts = _current_facts(frozen, registry)
    required = REQUIRED[trigger.event_type]
    missing = [key for key in required if key not in facts or facts[key]["value"] is not True]
    source = source_conflicts(frozen, selected)
    for tool, evidence_ids in [("case_timeline", []), ("evidence_lookup", [item["evidence_id"] for item in registry]), ("missing_fields", [])]:
        check()
        metrics["tool_calls"] += 1
        emit("tool.completed", "ROUTING", {"tool": tool, "evidence_ids": evidence_ids})
    initial, final, records, errors = [], {}, [], []

    def review(role, phase, peers, conflicts):
        check()
        stage = "DISCUSSION" if phase == "discussion" else "AGENTS_RUNNING"
        emit("agent.started", stage, {"phase": phase}, role)
        check()
        metrics["agent_calls"] += 1
        context = {"run_id": run_id, "case_id": frozen.case_id, "case_version": frozen.version,
                   "agent_id": role, "phase": phase, "current_question": frozen.current_question,
                   "trigger_event": trigger.model_dump(mode="json"), "events": [event.model_dump(mode="json") for event in frozen.timeline],
                   "evidence_registry": deepcopy(registry), "current_facts": {key: item["value"] for key, item in facts.items()},
                   "required_fields": required.copy(), "missing_information": missing.copy(),
                   "prior_opinion": deepcopy(final.get(role)), "peer_opinions": deepcopy(peers), "conflicts": deepcopy(conflicts)}
        try:
            raw = llm(context) if request.mode == "llm" else _mock(context, request.mock_scenario, selected[-1], selected)
            check()
            opinion = validate_output(raw, role, registry, f"op_{role}_{phase}")
        except WorkflowCancelled:
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, WorkflowError) else getattr(exc, "code", None)
            if code not in SAFE_ERRORS | {"invalid_evidence", "simulated_agent_failure"}:
                code = "invalid_opinion" if isinstance(exc, (ValidationError, ValueError)) else "agent_exception"
            errors.append({"agent_id": role, "phase": phase, "error_code": code})
            emit("agent.failed", stage, {"phase": phase, "error_code": code}, role)
            return None
        emit("agent.completed", stage, {"phase": phase, "opinion": opinion}, role)
        return opinion

    for role in selected:
        node = f"{role}_review"
        begin(node, "AGENTS_RUNNING")
        opinion = review(role, "initial", [], source)
        if opinion:
            initial.append(opinion)
            final[role] = opinion
        finish(node, "AGENTS_RUNNING")
    begin("conflict_detection", "CONFLICT_CHECK")
    conflicts = detect_conflicts(initial, source)
    emit("conflict.detected", "CONFLICT_CHECK", {"conflicts": conflicts})
    finish("conflict_detection", "CONFLICT_CHECK")
    participants = [role for role in selected if role in final and any(role in conflict["agent_ids"] for conflict in conflicts)]
    if participants:
        nodes.insert(nodes.index("safety_gate"), "targeted_discussion")
        begin("targeted_discussion", "DISCUSSION")
        emit("discussion.started", "DISCUSSION", {"round": 1, "participants": participants})
        peers = deepcopy(initial)
        for role in participants:
            before = final[role]
            after = review(role, "discussion", peers, conflicts)
            if after:
                final[role] = after
            else:
                final.pop(role, None)
            records.append({"agent_id": role, "before": before, "after": after,
                            "changed": after is None or before["decision"] != after["decision"] or before["claims"] != after["claims"]})
        emit("discussion.completed", "DISCUSSION", {"round": 1, "participants": participants})
        finish("targeted_discussion", "DISCUSSION")
    final_opinions = [final[role] for role in selected if role in final]
    unresolved = detect_conflicts(final_opinions, source)
    begin("safety_gate", "SAFETY_CHECK")
    missing = sorted(set(missing) | {item for opinion in final_opinions for item in opinion["missing_information"]})
    complete = len(final_opinions) == len(selected) and not errors
    valid_evidence = not any(error["error_code"] in {"invalid_evidence", "invalid_opinion", "LLM_INVALID_OUTPUT"} for error in errors)
    deferred = not complete or bool(unresolved) or any(opinion["decision"] == "DEFER_DECISION" for opinion in final_opinions)
    needs = bool(missing) or any(opinion["decision"] == "NEED_MORE_INFORMATION" for opinion in final_opinions)
    decision = "DEFER_DECISION" if deferred else "NEED_MORE_INFORMATION" if needs else "READY_FOR_REVIEW"
    checks = [
        {"code": "selected_agent_coverage", "status": "passed" if complete else "blocked", "message": f"有效最终意见 {len(final_opinions)} / 本次调度 {len(selected)}；跳过专科不计作失败。", "evidence_ids": []},
        {"code": "evidence_integrity", "status": "passed" if valid_evidence else "blocked", "message": "引用必须属于冻结上下文，事实键与值必须逐项匹配；只检验输入一致性。", "evidence_ids": []},
        {"code": "unresolved_conflicts", "status": "blocked" if unresolved else "passed", "message": f"保留 {len(unresolved)} 项未解决分歧；不采用多数票。", "evidence_ids": []},
        {"code": "required_information", "status": "warning" if missing else "passed", "message": "待补字段：" + "、".join(missing) if missing else "当前事件科研规则所需记录齐备。", "evidence_ids": []},
        {"code": "temporal_boundary", "status": "passed", "message": f"仅使用 v{frozen.version} 中截至 {trigger.event_id} 的 {len(frozen.timeline)} 条事件。", "evidence_ids": []},
    ]
    safety = Safety(decision=decision, status="blocked" if deferred else "needs_information" if needs else "passed",
                    checks=checks, missing_information=missing,
                    warnings=["Mock 为确定的科研流程脚本，不代表医学推理。" if request.mode == "mock" else "模型摘要仅供科研资料审阅，引用校验不能证明医学正确。"] +
                    [f"{error['agent_id']}/{error['phase']}: {error['error_code']}" for error in errors]).model_dump(mode="json")
    emit("safety.completed", "SAFETY_CHECK", safety)
    finish("safety_gate", "SAFETY_CHECK")
    begin("report", "REPORTING")
    if llm is not None:
        for key in ("llm_calls", "retry_count", "prompt_tokens", "completion_tokens"):
            metrics[key] = getattr(llm, "metrics", {}).get(key, metrics[key])
    metrics["elapsed_ms"] = (time.monotonic() - started) * 1000
    status = "failed" if not final_opinions else "incomplete" if errors else "completed"
    report = Report(
        run_id=run_id, **request.model_dump(), case_snapshot=frozen, routing=routing, evidence_registry=registry,
        initial_opinions=initial, final_opinions=final_opinions, conflicts=conflicts,
        unresolved_conflicts=unresolved, discussion_records=records, discussion_rounds=int(bool(participants)),
        safety=safety, final_decision=decision, status=status, metrics=metrics,
    ).model_dump(mode="json")
    finish("report", "REPORTING")
    return report
