"""Case-driven automated medical workflow designer, multi-modal imaging pipeline,
semantic completeness inference, and B0-B3 ablation experiment matrix.

This module bridges external public datasets (Synthea, TCIA NSCLC-Radiogenomics)
and synthetic cases with traceable imaging metadata, automated
workflow DAG generation, and controlled single-factor ablation comparisons.
"""

from __future__ import annotations

from collections import Counter

from .consensus_metrics import compute_specialist_utilities
from .engine import (
    REQUIRED,
    ROUTES,
    current_fact_records,
    current_fact_values,
    execute,
    freeze_context,
    single_mock_review,
    source_conflicts,
)
from .schemas import ROLES, ClinicalEvent, ResearchCase, RunRequest, case_with_synthetic_event

WORKFLOW_DESIGNER_VERSION = "case-adaptive-workflow-v2"
IMAGING_PIPELINE_VERSION = "imaging-records-v2"

FACT_LABELS_ZH: dict[str, str] = {
    "imaging_complete": "影像资料齐备",
    "imaging_record": "影像检查记录",
    "pathology_confirmed": "病理学已确诊",
    "pathology_record": "病理报告记录",
    "histology": "组织学病理分型",
    "molecular_complete": "分子检测齐备",
    "molecular_record": "分子基因检测记录",
    "procedure_record_complete": "手术与操作记录齐备",
    "treatment_record_complete": "治疗方案记录齐备",
    "toxicity_assessed": "不良反应已评估",
    "follow_up_complete": "随访资料齐备",
    "follow_up_record": "随访观察记录",
    "progression_confirmed": "疾病进展已确认",
    "progression_event_received": "进展复核触发标记",
    "observation_reviewed": "临床观察已审阅",
    "disease_label": "疾病诊断标签",
    "record_note": "记录核对备注",
    "review_note": "人工复核说明",
    "supersedes_event_id": "替代历史事件编号",
    "modality": "影像检查模态",
    "recorded_date": "原始记录日期",
    "source_subject_id": "来源受试者编号",
    "original_date": "原始日期文本",
    "code": "医学标准编码",
    "description": "临床检查/诊断描述",
    "coding_system": "编码体系",
    "unit": "计量单位",
    "encounter_id": "就诊记录编号",
    "body_site": "解剖部位",
    "category": "记录类别",
    "record_type": "就诊类别",
    "observed_value": "临床观测结果",
    "pathological_t": "病理 T 分期（原发肿瘤）",
    "pathological_n": "病理 N 分期（区域淋巴结）",
    "pathological_m": "病理 M 分期（远处转移）",
    "grade": "组织学分化分级",
    "smoking_status": "吸烟史状态",
    "egfr_status": "EGFR 基因突变状态",
    "kras_status": "KRAS 基因突变状态",
    "alk_status": "ALK 融合重排状态",
    "adjuvant_treatment": "术后辅助治疗",
    "chemotherapy": "化疗方案记录",
    "radiation": "放疗方案记录",
    "recurrence_status": "复发状态汇总",
    "survival_status": "生存结局状态",
    "imaging_qc_passed": "影像质控核验通过",
    "lesion_diameter_mm": "主病灶最大长径 (mm)",
    "radiomics_suvmax": "PET 代谢峰值 (SUVmax)",
}

ROLE_LABELS_ZH: dict[str, str] = {
    "oncology": "肿瘤内科",
    "radiology": "影像科",
    "surgery": "胸外科",
    "pathology": "病理科",
}

PHASE_BY_EVENT: dict[str, str] = {
    "diagnosis": "初诊基线多学科综合评估",
    "imaging": "影像检查记录复核",
    "pathology": "组织病理学确诊与分型审阅",
    "molecular_test": "分子病理与驱动基因靶点会诊",
    "procedure": "胸外科手术与有创操作记录复核",
    "treatment": "综合抗肿瘤治疗方案审阅",
    "medication": "药物治疗记录与依从性审阅",
    "toxicity": "治疗相关不良反应与安全性评估",
    "follow_up": "纵向随访监测与影像对比复核",
    "progression": "疾病进展多学科鉴别与证据门控",
    "recurrence": "肿瘤复发多学科全面复核",
    "observation": "常规临床观察指标审阅",
}

# Only explicit, structured histology results in a dated pathology record are eligible.
# Free text, diagnosis codes, a scan registration and unplaced cohort columns are insufficient.
PATHOLOGY_HISTOLOGIES = {
    "adenocarcinoma", "squamous cell carcinoma", "large cell carcinoma",
    "肺腺癌", "腺癌", "肺鳞状细胞癌", "鳞状细胞癌", "肺大细胞癌", "大细胞癌",
}
HISTOLOGY_RULE = "dated_pathology_histology_v1"
EVENT_ID_ALPHABET = "-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"


def _resolve_trigger_id(case: ResearchCase, trigger_event_id: str | None) -> str:
    # freeze_context rejects an explicitly supplied unknown ID.
    return case.timeline[-1].event_id if trigger_event_id is None else trigger_event_id


def _adjacent_extension_id(case: ResearchCase, trigger: ClinicalEvent) -> str | None:
    """Find an ID directly after the trigger without crossing any same-day event."""
    by_id = {event.event_id: event for event in case.timeline}
    candidate = trigger.event_id
    while True:
        if len(candidate) < 80:
            candidate += EVENT_ID_ALPHABET[0]
        else:
            prefix = candidate.rstrip(EVENT_ID_ALPHABET[-1])
            if not prefix:
                return None
            candidate = prefix[:-1] + EVENT_ID_ALPHABET[EVENT_ID_ALPHABET.index(prefix[-1]) + 1]
        existing = by_id.get(candidate)
        if existing is None:
            return candidate
        if existing.occurred_at == trigger.occurred_at:
            return None


def _dated_pathology_result(frozen: ResearchCase, current, latest) -> ClinicalEvent | None:
    records = current.get("histology")
    value = latest.get("histology")
    if not records or not isinstance(value, str) or value.strip().casefold() not in PATHOLOGY_HISTOLOGIES:
        return None
    source = records[-1]
    if source.event_type != "pathology" or any(
        event.facts["histology_missing_reason"] and event.occurred_at >= source.occurred_at
        for event in current.get("histology_missing_reason", [])
    ):
        return None
    if any(event.facts.get("supersedes_event_id") == source.event_id for event in frozen.timeline):
        return None
    return source


def infer_semantic_completeness(case: ResearchCase, trigger_event_id: str | None = None) -> dict:
    frozen = freeze_context(case, _resolve_trigger_id(case, trigger_event_id))
    trigger = frozen.timeline[-1]
    required = REQUIRED[trigger.event_type]
    current = current_fact_records(frozen)
    latest = current_fact_values(current)
    strict_missing = [key for key in required if latest.get(key) is not True]
    inferred = []
    if ("pathology_confirmed" in strict_missing and "pathology_confirmed" not in current
            and "pathology_confirmed_missing_reason" not in current):
        source = _dated_pathology_result(frozen, current, latest)
        if source is not None:
            evidence_id = f"{source.event_id}:histology"
            inferred.append({
                "fact_key": "pathology_confirmed", "fact_label": FACT_LABELS_ZH["pathology_confirmed"],
                "inferred_value": True, "confidence": "derived", "rule_id": HISTOLOGY_RULE,
                "source_event_id": source.event_id, "source_evidence_id": evidence_id,
                "reason": f"{source.occurred_at} 的病理事件载有明确组织学分型，依据 {evidence_id} 映射研究资料标记。",
            })

    recommended = {item["fact_key"]: item["inferred_value"] for item in inferred}
    post_missing = [key for key in strict_missing if key not in recommended]
    generator = next((src for src in case.provenance if src.source_name == "research_scenario_generator"), None)
    has_source_slot = generator.synthetic if generator is not None else len(case.provenance) < 100
    extension_id = None
    if recommended and len(case.timeline) < 1000 and has_source_slot:
        extension_id = _adjacent_extension_id(case, trigger)
    return {
        "trigger_event_id": trigger.event_id,
        "trigger_event_type": trigger.event_type,
        "required_fields": [
            {"fact_key": key, "fact_label": FACT_LABELS_ZH.get(key, key),
             "strict_satisfied": key not in strict_missing, "semantic_satisfied": key not in post_missing}
            for key in required
        ],
        "strict_missing": strict_missing,
        "strict_missing_labels": [FACT_LABELS_ZH.get(key, key) for key in strict_missing],
        "semantic_inferred": inferred,
        "post_inference_missing": post_missing,
        "post_inference_missing_labels": [FACT_LABELS_ZH.get(key, key) for key in post_missing],
        "strict_completeness_score": round(100 * (len(required) - len(strict_missing)) / len(required)),
        "semantic_completeness_score": round(100 * (len(required) - len(post_missing)) / len(required)),
        "can_auto_enrich": extension_id is not None,
        "recommended_facts": recommended,
        "extension_event_id": extension_id,
    }


def semantic_extension(case: ResearchCase, completeness: dict) -> dict:
    """Prepare an append-only event with a reproducible reference for each derived field."""
    if not completeness["can_auto_enrich"]:
        raise ValueError("No supported semantic extension is available")
    trigger = next(event for event in case.timeline if event.event_id == completeness["trigger_event_id"])
    return {
        "event_id": completeness["extension_event_id"], "occurred_at": trigger.occurred_at.isoformat(),
        "event_type": trigger.event_type, "title": f"基于 {trigger.event_id} 已有证据的研究标记补齐",
        "facts": completeness["recommended_facts"],
        "source_record_locator": f"{case.case_id}@v{case.version}/{trigger.event_id}",
        "source_fields": {item["fact_key"]: item["source_evidence_id"] for item in completeness["semantic_inferred"]},
        "time_note": f"按 {HISTOLOGY_RULE} 派生；与触发事件同日，技术排序紧随该截点。",
    }


def build_semantic_version(case: ResearchCase, completeness: dict) -> tuple[ResearchCase, str]:
    """Build the same isolated revision used by the append-only enrichment endpoint."""
    event = semantic_extension(case, completeness)
    payload, created = case_with_synthetic_event(case.model_dump(mode="json"), event)
    return ResearchCase.model_validate(payload), created["event_id"]


def process_case_imaging(case: ResearchCase, trigger_event_id: str | None = None) -> dict:
    """List source-backed imaging records visible at the cutoff. Inputs contain no pixels."""
    target_id = _resolve_trigger_id(case, trigger_event_id)
    frozen = freeze_context(case, target_id)
    sources = {source.source_name: source for source in frozen.provenance}

    # Associate each conflict with the records and fields actually named by the evidence.
    conflict_refs: dict[str, list[str]] = {}
    for conflict in source_conflicts(frozen, list(ROLES)):
        refs = conflict["evidence_ids"]
        for ref in refs:
            event_id, key = ref.split(":", 1)
            if key in {"imaging_complete", "progression_confirmed"}:
                conflict_refs.setdefault(event_id, []).extend(refs)

    studies = []
    for event in frozen.timeline:
        if event.event_type != "imaging" and not any(key in event.facts for key in ("modality", "imaging_record")):
            continue
        source = sources[event.source]
        refs = conflict_refs.get(event.event_id, [])
        if refs:
            record_status = "conflict"
        elif event.facts.get("imaging_complete") is False:
            record_status = "incomplete"
        else:
            record_status = "documented"
        # Research JSON can contain arbitrary scalar values. Only use strings as display labels.
        modality = event.facts.get("modality")
        site = event.facts.get("body_site")
        studies.append({
            "study_id": f"IMG_{event.event_id}",
            "event_id": event.event_id,
            "occurred_at": event.occurred_at.isoformat(),
            "title": event.title,
            "modality": modality if isinstance(modality, str) and modality.strip() else None,
            "anatomical_site": site if isinstance(site, str) and site.strip() else None,
            "source_name": source.source_name,
            "dataset_version": source.dataset_version,
            "synthetic": source.synthetic,
            "artifact_sha256": source.artifact_sha256,
            "source_record_id": event.source_record_id,
            "source_record_locator": event.source_record_locator,
            "record_status": record_status,
            "conflict_evidence_ids": list(dict.fromkeys(refs)),
            "record_fields": [
                {"fact_key": key, "value": event.facts[key], "evidence_id": f"{event.event_id}:{key}",
                 "source_field": event.source_fields.get(key)}
                for key in ("modality", "body_site", "recorded_date", "description", "imaging_record",
                            "imaging_complete", "progression_confirmed") if key in event.facts
            ],
            "qc_status": "not_assessed",
            "qc_score": None,
            "dicom_metadata": None,
            "radiomics": None,
            "svg_slice": None,
        })

    statuses = {study["record_status"] for study in studies}
    overall = next((status for status in ("conflict", "incomplete", "documented") if status in statuses), "no_studies")
    return {
        "case_id": case.case_id,
        "case_version": case.version,
        "trigger_event_id": target_id,
        "pipeline_version": IMAGING_PIPELINE_VERSION,
        "input_kind": "event_metadata",
        "study_count": len(studies),
        "overall_record_status": overall,
        "overall_qc_status": "not_assessed",
        "studies": studies,
    }


def design_medical_workflow(case: ResearchCase, trigger_event_id: str | None = None) -> dict:
    """Automatically design a customized end-to-end medical MDT workflow based on case characteristics."""
    target_id = _resolve_trigger_id(case, trigger_event_id)
    frozen = freeze_context(case, target_id)
    trigger = frozen.timeline[-1]
    completeness = infer_semantic_completeness(case, target_id)
    imaging = process_case_imaging(case, target_id)
    conflicts = source_conflicts(frozen, list(ROLES))

    base_selected = ROUTES[trigger.event_type].copy()
    util = compute_specialist_utilities(frozen)
    util_by_role = {item["agent_id"]: item for item in util["utilities"]}
    adaptive_selected = [
        role for role in ROLES
        if role in set(base_selected) | set(util["selected_agents"])
    ]
    adaptive_reasons: list[dict] = []

    role_tasks_map = {
        "oncology": {
            "focus": "统筹全病程诊疗时间线、评估系统治疗指征与关键资料完备性",
            "tasks": [
                f"核对截至 {trigger.event_id}（{trigger.occurred_at}）的 {len(frozen.timeline)} 条纵向病程事件",
                "审查肿瘤分期、基因靶点及全身治疗前基线完备度",
                "对跨专科分歧或缺失字段发起补件或暂缓建议",
            ],
        },
        "radiology": {
            "focus": "核对影像登记的日期、来源和资料缺口",
            "tasks": [
                f"审阅 {imaging['study_count']} 条影像登记及其原始字段",
                "核查同日影像记录之间的矛盾和证据编号",
                "记录需要补充的检查报告或影像附件",
            ],
        },
        "pathology": {
            "focus": "核验组织学病理分型、免疫组化及驱动基因（EGFR/KRAS/ALK）分子检测完备性",
            "tasks": [
                "核对组织学确诊记录与标本来源一致性",
                "检查分子病理检测报告是否归档且无占位缺失",
                "识别未定位时间的基线病理记录并给出补件指引",
            ],
        },
        "surgery": {
            "focus": "评估外科可切除性边界、围手术期操作记录与局部复发风险",
            "tasks": [
                "核对手术/有创操作记录及病理切缘、TNM 分期一致性",
                "核对已有影像登记与围手术期资料的时间顺序",
            ],
        },
    }

    for role in ROLES:
        in_base = role in base_selected
        in_adaptive = role in adaptive_selected
        info = role_tasks_map[role]
        role_util = util_by_role[role]
        adaptive_reasons.append({
            "agent_id": role,
            "agent_label": ROLE_LABELS_ZH[role],
            "selected": in_adaptive,
            "routing_type": "基础事件命中" if in_base else "风险效用自适应增补" if in_adaptive else "本计划未建议",
            "focus": info["focus"],
            "clinical_tasks": info["tasks"] if in_adaptive else ["当前计划中未列出该专科的审阅任务。"],
            "utility_score": role_util["utility_score"],
            "utility_signals": role_util["signals"],
        })

    if conflicts:
        complexity = "high_risk"
        complexity_label = "高危冲突阻断态"
    elif completeness["strict_missing"]:
        complexity = "elevated"
        complexity_label = "资料待补核查态"
    else:
        complexity = "standard"
        complexity_label = "标准齐备复核态"

    workflow_stages = [
        {
            "stage_id": "stage_intake_freeze",
            "step_number": 1,
            "title": "纵向病程冻结与防泄漏截断",
            "category": "ingestion",
            "status": "active",
            "automated_operator": "freeze_context",
            "description": f"锁定 v{frozen.version} 截至 {trigger.event_id}（{trigger.occurred_at}）的 {len(frozen.timeline)} 条事件，自动隔离 {len(case.timeline) - len(frozen.timeline)} 条未来事件与 {len(case.unplaced_records)} 组无日期记录。",
        },
        {
            "stage_id": "stage_imaging_pipeline",
            "step_number": 2,
            "title": "影像检查登记与来源核对",
            "category": "imaging",
            "status": "active" if imaging["study_count"] > 0 else "skipped",
            "automated_operator": "process_case_imaging",
            "description": (
                f"截至触发点共 {imaging['study_count']} 条影像登记，可核对来源及同日相反记录。当前输入仅包含事件元数据。"
                if imaging["study_count"] > 0
                else "当前截点前没有影像检查登记。"
            ),
        },
        {
            "stage_id": "stage_semantic_align",
            "step_number": 3,
            "title": "跨源临床语义归一化与完备度推导",
            "category": "semantic",
            "status": "active" if completeness["semantic_inferred"] or case.case_kind != "synthetic" else "recommended",
            "automated_operator": "infer_semantic_completeness",
            "description": (
                f"从原始临床/影像表自动推导 {len(completeness['semantic_inferred'])} 项完备性指标，资料完备度从 {completeness['strict_completeness_score']}% 提升至 {completeness['semantic_completeness_score']}%。"
                if completeness["semantic_inferred"]
                else f"结构化事实直接匹配科研规则，当前严格资料完备度为 {completeness['strict_completeness_score']}%。"
            ),
        },
        {
            "stage_id": "stage_specialist_dispatch",
            "step_number": 4,
            "title": "按病例资料建议参与专科",
            "category": "specialist",
            "status": "active",
            "automated_operator": "design_medical_workflow",
            "description": f"针对「{PHASE_BY_EVENT.get(trigger.event_type, trigger.event_type)}」阶段，建议 {'、'.join(ROLE_LABELS_ZH[r] for r in adaptive_selected)}（共 {len(adaptive_selected)}/{len(ROLES)} 科）参与。实际运行按事件路由或固定全员配置选取专科。",
        },
        {
            "stage_id": "stage_conflict_arbitration",
            "step_number": 5,
            "title": "多维分歧检测与有界定向协商",
            "category": "negotiation",
            "status": "active" if conflicts or completeness["strict_missing"] else "recommended",
            "automated_operator": "detect_conflicts",
            "description": (
                f"已检测到 {len(conflicts)} 项底层同日来源矛盾，将触发最多 1 轮跨科定向协商并禁止多数票掩盖冲突。"
                if conflicts
                else "独立初审后自动比对流程标签与结构化事实断言；若存在分歧则启动单轮快照隔离协商。"
            ),
        },
        {
            "stage_id": "stage_safety_gate",
            "step_number": 6,
            "title": "证据链溯源与医疗安全门控",
            "category": "gate",
            "status": "active",
            "automated_operator": "safety_gate",
            "description": "逐项核验引用 ID、事实类型、未解冲突与必需字段，输出最终审阅标签与可复现审计快照。",
        },
    ]

    strict_predicted = (
        "DEFER_DECISION" if conflicts
        else "NEED_MORE_INFORMATION" if completeness["strict_missing"]
        else "READY_FOR_REVIEW"
    )
    semantic_predicted = (
        "DEFER_DECISION" if conflicts
        else "NEED_MORE_INFORMATION" if completeness["post_inference_missing"]
        else "READY_FOR_REVIEW"
    )

    return {
        "workflow_id": f"wf_{case.case_id}_v{case.version}_{target_id}",
        "case_id": case.case_id,
        "case_version": case.version,
        "trigger_event_id": target_id,
        "trigger_event_title": trigger.title,
        "trigger_event_type": trigger.event_type,
        "strategy_version": WORKFLOW_DESIGNER_VERSION,
        "clinical_phase": PHASE_BY_EVENT.get(trigger.event_type, "多学科综合资料审阅"),
        "complexity_level": complexity,
        "complexity_label": complexity_label,
        "visible_event_count": len(frozen.timeline),
        "excluded_future_event_count": len(case.timeline) - len(frozen.timeline),
        "unplaced_record_count": len(case.unplaced_records),
        "source_conflict_count": len(conflicts),
        "selected_agents": adaptive_selected,
        "specialist_plan": adaptive_reasons,
        "workflow_stages": workflow_stages,
        "completeness": completeness,
        "imaging_summary": {
            "study_count": imaging["study_count"],
            "overall_qc_status": imaging["overall_qc_status"],
            "overall_record_status": imaging["overall_record_status"],
        },
        "predicted_decisions": {
            "strict_rule_decision": strict_predicted,
            "semantic_enriched_decision": semantic_predicted,
        },
    }


def _plurality(opinions: list[dict]) -> str | None:
    """Plurality of valid opinions, deferral on ties, no output on an empty set."""
    counts = Counter(opinion["decision"] for opinion in opinions).most_common(2)
    if not counts:
        return None
    if len(counts) == 2 and counts[0][1] == counts[1][1]:
        return "DEFER_DECISION"
    return counts[0][0]


def _mock_trajectory(case: ResearchCase, trigger_id: str, method_id: str, *,
                     routing: str = "event", discussion: bool = True) -> dict:
    request = RunRequest(case_id=case.case_id, case_version=case.version, trigger_event_id=trigger_id,
                         mode="mock", routing_mode=routing)
    report = execute(case, request, method_id, lambda *args: None, lambda: False, allow_discussion=discussion)
    successful_calls = len(report["initial_opinions"]) + sum(
        record["after"] is not None for record in report["discussion_records"]
    )
    return {
        "trajectory_id": method_id,
        "input_case_version": case.version, "input_trigger_event_id": trigger_id,
        "visible_events": len(report["case_snapshot"]["timeline"]),
        "selected_agents": report["routing"]["selected_agents"],
        "agent_calls": report["metrics"]["agent_calls"], "discussion_rounds": report["discussion_rounds"],
        "valid_opinions": len(report["final_opinions"]),
        "failed_calls": report["metrics"]["agent_calls"] - successful_calls,
        "pre_gate_decision": _plurality(report["final_opinions"]), "final_decision": report["final_decision"],
        "missing_count": len(report["safety"]["missing_information"]),
        "unresolved_conflicts": len(report["unresolved_conflicts"]),
    }


def _method_row(method_id: str, name: str, category: str, strategy: str, trace: dict,
                note: str, *, gate: bool) -> dict:
    return {
        **trace, "method_id": method_id, "name": f"{method_id} · {name}", "category": category,
        "routing_strategy": strategy, "key_finding": note, "gate_applied": gate,
        "final_decision": trace["final_decision"] if gate else trace["pre_gate_decision"],
    }


def evaluate_ablation_matrix(case: ResearchCase, trigger_event_id: str | None = None) -> dict:
    """Paired deterministic process checks. No model endpoint or reference labels are used."""
    target_id = _resolve_trigger_id(case, trigger_event_id)
    frozen = freeze_context(case, target_id)
    b0 = {
        **single_mock_review(frozen), "trajectory_id": "B0", "input_case_version": frozen.version,
        "input_trigger_event_id": target_id, "visible_events": len(frozen.timeline),
    }
    b1 = _mock_trajectory(frozen, target_id, "B1", routing="fixed", discussion=False)
    shared = _mock_trajectory(frozen, target_id, "B3")

    trigger_only = frozen.model_copy(update={"timeline": [frozen.timeline[-1]]})
    memory = _mock_trajectory(trigger_only, target_id, "A1")
    fixed = _mock_trajectory(frozen, target_id, "A3", routing="fixed")
    no_discussion = _mock_trajectory(frozen, target_id, "A4", discussion=False)

    # Future event IDs and timeline capacity must not influence this offline extension.
    completeness = infer_semantic_completeness(frozen, target_id)
    semantic = shared
    semantic_note = "当前截点无可写入的派生版本，沿用 B3 的输入和读数。"
    if completeness["can_auto_enrich"]:
        enriched, extension_id = build_semantic_version(frozen, completeness)
        semantic = _mock_trajectory(enriched, extension_id, "A2")
        semantic_note = f"在内存中追加有来源的派生事件 {extension_id}，按扩展截点复核资料。"

    methods = [
        _method_row("B0", "单审阅者", "基线对照", "通用审阅", b0,
                    "通用角色独立执行一次规则审阅，读取共同的冻结资料、缺件和来源冲突提示。", gate=False),
        _method_row("B1", "固定全员无协商", "基线对照", "固定四专科", b1,
                    "四科各完成一次初审，以有效意见的相对多数给出方法结论。", gate=False),
        _method_row("B2", "事件路由与定向协商", "基线对照", "事件路由", shared,
                    "与 B3 共享审阅轨迹，在门控前对最终有效意见取相对多数。", gate=False),
        _method_row("B3", "完整工作流", "基线对照", "事件路由", shared,
                    "对同一批意见核查角色覆盖、证据、缺件和未解分歧，记录门控标签。", gate=True),
        _method_row("A1", "仅当前事件", "单因素消融", "事件路由", memory,
                    f"相对 B3 移除 {len(frozen.timeline) - 1} 条更早事件，重新建立证据表。", gate=True),
        _method_row("A2", "可溯源语义补齐", "扩展场景", "事件路由", semantic, semantic_note, gate=True),
        _method_row("A3", "固定全员", "单因素消融", "固定四专科", fixed,
                    "相对 B3 仅改变路由，保留冲突检测、定向协商和门控。", gate=True),
        _method_row("A4", "关闭协商", "单因素消融", "事件路由", no_discussion,
                    "相对 B3 仅关闭讨论轮次，保留初审分歧检测和最终门控。", gate=True),
    ]
    return {
        "protocol_version": "mock-matrix-v2", "execution_mode": "mock",
        "case_id": case.case_id, "case_version": case.version, "trigger_event_id": target_id,
        "visible_events": len(frozen.timeline), "methods": methods,
        "fixed_total_calls": fixed["agent_calls"], "routed_total_calls": shared["agent_calls"],
        "call_saving_pct": round(100 * (fixed["agent_calls"] - shared["agent_calls"]) / fixed["agent_calls"]),
    }
