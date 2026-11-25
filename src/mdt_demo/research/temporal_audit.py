"""Independent temporal-boundary leakage auditor (Plan §1 & §6.3).

Reconstructs the legal historical fact whitelist directly from the full source
ResearchCase without calling engine.freeze_context, then verifies case snapshots,
evidence registries, opinion citations, and free-text questions against that whitelist.
"""

from __future__ import annotations

from datetime import date
import json
import re

from .schemas import ClinicalEvent, EvidenceRef, ResearchCase

AUDIT_VERSION = "temporal-boundary-audit-v2"
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _expected_references(case: ResearchCase, events: dict[str, dict]) -> dict[str, dict]:
    """Reconstruct each citation from the source event and its dataset declaration."""
    sources = {source.source_name: source for source in case.provenance}
    refs = {}
    for event in events.values():
        source = sources[event["source"]]
        for key, value in event["facts"].items():
            evidence_id = f"{event['event_id']}:{key}"
            refs[evidence_id] = {
                "evidence_id": evidence_id, "event_id": event["event_id"], "fact_key": key, "value": value,
                "source_name": source.source_name, "source_record_id": event["source_record_id"],
                "dataset_version": source.dataset_version, "synthetic": source.synthetic,
                "artifact_sha256": source.artifact_sha256, "source_record_locator": event["source_record_locator"],
                "source_field": event["source_fields"].get(key),
                "quote_or_fact": f"{key} = {json.dumps(value, ensure_ascii=False, allow_nan=False)}",
            }
    return refs


def _scan_question_future_dates(question: str, cutoff_date: date) -> list[str]:
    future_dates: list[str] = []
    for match in ISO_DATE_RE.findall(question or ""):
        try:
            parsed = date.fromisoformat(match)
        except ValueError:
            continue
        if parsed > cutoff_date and match not in future_dates:
            future_dates.append(match)
    return future_dates


def _same_value(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_value(left[key], right[key]) for key in left)
    return left == right


def _defaults(model) -> dict:
    # Older snapshots may omit a newly introduced field whose value is its schema default.
    return {name: field.get_default(call_default_factory=True) for name, field in model.model_fields.items()
            if not field.is_required()}


_EVENT_DEFAULTS = _defaults(ClinicalEvent)
_REF_DEFAULTS = _defaults(EvidenceRef)


def _issue(code: str, location: str, item_id: object, detail: str) -> dict:
    return {"check_code": code, "location": location, "item_id": str(item_id), "detail": detail}


def _audit_rows(rows, expected: dict[str, dict], id_field: str, defaults: dict,
                code: str, location: str, *, ordered: bool = False) -> list[dict]:
    """Check that each expected record appears exactly once with its original content."""
    if not isinstance(rows, list):
        return [_issue(code, location, location, "缺少有效的记录列表。")]
    issues = []
    seen = set()
    for index, row in enumerate(rows):
        item_id = row.get(id_field) if isinstance(row, dict) else None
        row_loc = f"{location}[{index}]"
        if not isinstance(item_id, str) or item_id not in expected:
            issues.append(_issue(code, row_loc, item_id, "记录缺少有效编号或不属于本截点允许的记录。"))
            continue
        if item_id in seen:
            issues.append(_issue(code, row_loc, item_id, "同一编号的记录重复出现。"))
        seen.add(item_id)
        if not _same_value({**defaults, **row}, expected[item_id]):
            issues.append(_issue(code, row_loc, item_id, "记录内容、事实类型或来源与原病例版本不一致。"))
    for item_id in expected:
        if item_id not in seen:
            issues.append(_issue(code, location, item_id, "缺少该截点应有的记录。"))
    if ordered and not issues and [row[id_field] for row in rows] != list(expected):
        issues.append(_issue(code, location, location, "快照事件顺序与原病例历史截点不一致。"))
    return issues


def _audit_opinion(op, loc: str, expected: dict[str, dict]) -> tuple[list[dict], int, int]:
    code = "opinion_citation_boundary"
    if not isinstance(op, dict):
        return [_issue(code, loc, loc, "缺少有效的意见记录。")], 0, 0
    ids = op.get("evidence_ids")
    claims = op.get("claims")
    issues = []
    if not isinstance(ids, list) or not ids:
        issues.append(_issue(code, f"{loc}.evidence_ids", loc, "意见缺少有效的引用编号列表。"))
        ids = []
    if not isinstance(claims, list) or not claims:
        issues.append(_issue(code, f"{loc}.claims", loc, "意见缺少有效的结构化断言。"))
        claims = []
    cited = {}
    for evidence_id in ids:
        if not isinstance(evidence_id, str) or evidence_id not in expected:
            issues.append(_issue(code, f"{loc}.evidence_ids", evidence_id, "引用不在原病例的截点内。"))
        elif evidence_id in cited:
            issues.append(_issue(code, f"{loc}.evidence_ids", evidence_id, "同一意见重复声明了引用编号。"))
        else:
            cited[evidence_id] = expected[evidence_id]
    issues.extend(_audit_rows(op.get("evidence_refs"), cited, "evidence_id", _REF_DEFAULTS,
                              code, f"{loc}.evidence_refs"))
    for index, claim in enumerate(claims):
        evidence_id = claim.get("evidence_id") if isinstance(claim, dict) else None
        target = cited.get(evidence_id) if isinstance(evidence_id, str) else None
        if target is None or not _same_value(claim, {key: target[key] for key in ("evidence_id", "fact_key", "value")}):
            issues.append(_issue(code, f"{loc}.claims[{index}]", evidence_id,
                                 "断言须引用本意见已声明的证据，事实键、值及类型均须与原病例相符。"))
    return issues, len(ids), len(claims)


def audit_temporal_boundary(original_case: ResearchCase, report: dict) -> dict:
    """Independently audit a run Report against the original full ResearchCase."""
    return _audit(original_case, report["trigger_event_id"], report.get("case_snapshot"), report)


def audit_frozen_snapshot(original_case: ResearchCase, frozen: ResearchCase, trigger_event_id: str) -> dict:
    """Audit only the input before execution, when there is no report or registry yet."""
    return _audit(original_case, trigger_event_id, frozen.model_dump(mode="json"), None)


def _audit(original_case: ResearchCase, trigger_event_id: str, snapshot, report: dict | None) -> dict:
    trigger = next((event for event in original_case.timeline if event.event_id == trigger_event_id), None)
    if trigger is None:
        raise ValueError(f"触发事件 {trigger_event_id} 不存在于原始病例 {original_case.case_id} v{original_case.version}。")
    cutoff = (trigger.occurred_at, trigger.event_id)
    allowed_events = {event.event_id: event.model_dump(mode="json") for event in original_case.timeline
                      if (event.occurred_at, event.event_id) <= cutoff}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    leaked = _audit_rows(snapshot.get("timeline"), allowed_events, "event_id", _EVENT_DEFAULTS,
                         "snapshot_timeline_boundary", "case_snapshot.timeline", ordered=True)
    for key in ("case_id", "version", "current_question"):
        if not _same_value(snapshot.get(key), getattr(original_case, key)):
            leaked.append(_issue("snapshot_timeline_boundary", f"case_snapshot.{key}", key,
                                 "冻结输入的病例标识、版本或研究问题与原病例版本不一致。"))
    unplaced = snapshot.get("unplaced_records", [])
    if not isinstance(unplaced, list):
        leaked.append(_issue("unplaced_records_isolated", "case_snapshot.unplaced_records", "unplaced_records",
                             "无日期记录列表格式无效。"))
    else:
        for rec in unplaced:
            record_id = rec.get("record_id") if isinstance(rec, dict) else None
            leaked.append(_issue("unplaced_records_isolated", "case_snapshot.unplaced_records", record_id,
                                 "无可用日期的记录泄漏进入历史运行快照。"))

    registry_count = audited_citations = audited_claims = 0
    if report is not None:
        expected = _expected_references(original_case, allowed_events)
        registry = report.get("evidence_registry")
        registry_count = len(registry) if isinstance(registry, list) else 0
        leaked.extend(_audit_rows(registry, expected, "evidence_id", _REF_DEFAULTS,
                                  "evidence_registry_boundary", "evidence_registry"))
        for section in ("initial_opinions", "final_opinions", "discussion_records"):
            entries = report.get(section)
            if not isinstance(entries, list):
                leaked.append(_issue("opinion_citation_boundary", section, section, "缺少有效的意见记录列表。"))
                continue
            for index, entry in enumerate(entries):
                loc = f"{section}[{index}]"
                opinions = [(loc, entry)]
                if section == "discussion_records" and isinstance(entry, dict):
                    opinions = [(f"{loc}.before", entry.get("before"))]
                    if entry.get("after") is not None:
                        opinions.append((f"{loc}.after", entry["after"]))
                for op_loc, opinion in opinions:
                    issues, citations, claims = _audit_opinion(opinion, op_loc, expected)
                    leaked.extend(issues)
                    audited_citations += citations
                    audited_claims += claims

    # 5 & 6. Advisory checks: same-day ordering & future dates in free-text question
    same_day = [event.event_id for event in original_case.timeline if event.occurred_at == trigger.occurred_at]
    future_dates = _scan_question_future_dates(
        str(snapshot.get("current_question") or original_case.current_question),
        trigger.occurred_at,
    )

    hard_codes = {
        "snapshot_timeline_boundary",
        "unplaced_records_isolated",
        "evidence_registry_boundary",
        "opinion_citation_boundary",
    }
    leaked_by_code = {code: [item for item in leaked if item["check_code"] == code] for code in hard_codes}

    checks = [
        {
            "code": "snapshot_timeline_boundary",
            "status": "failed" if leaked_by_code["snapshot_timeline_boundary"] else "passed",
            "message": (
                f"发现 {len(leaked_by_code['snapshot_timeline_boundary'])} 项时间线截断异常。"
                if leaked_by_code["snapshot_timeline_boundary"]
                else f"独立重建验证通过：保留 {len(allowed_events)} 条截点前事件，屏蔽 {len(original_case.timeline) - len(allowed_events)} 条未来事件。"
            ),
        },
        {
            "code": "unplaced_records_isolated",
            "status": "failed" if leaked_by_code["unplaced_records_isolated"] else "passed",
            "message": (
                f"发现 {len(leaked_by_code['unplaced_records_isolated'])} 组无日期记录泄漏。"
                if leaked_by_code["unplaced_records_isolated"]
                else f"原始病例的 {len(original_case.unplaced_records)} 组无日期记录已全部隔离。"
            ),
        },
        {
            "code": "evidence_registry_boundary",
            "status": "failed" if leaked_by_code["evidence_registry_boundary"] else "passed",
            "message": (
                f"证据注册表发现 {len(leaked_by_code['evidence_registry_boundary'])} 项越界或不匹配。"
                if leaked_by_code["evidence_registry_boundary"]
                else f"证据注册表全部 {registry_count} 项事实均与原病例截点事实逐项匹配。"
            ),
        },
        {
            "code": "opinion_citation_boundary",
            "status": "failed" if leaked_by_code["opinion_citation_boundary"] else "passed",
            "message": (
                f"意见与断言中发现 {len(leaked_by_code['opinion_citation_boundary'])} 项越界引用。"
                if leaked_by_code["opinion_citation_boundary"]
                else f"全部 {audited_citations} 次引用与 {audited_claims} 条结构化断言均在合法历史边界内。"
            ),
        },
        {
            "code": "same_day_ordering_notice",
            "status": "warning" if len(same_day) > 1 else "passed",
            "message": (
                f"截点当日（{trigger.occurred_at}）存在 {len(same_day)} 条同日事件（{', '.join(same_day)}），同日先后按事件编号技术排序，请人工复核临床先后关系。"
                if len(same_day) > 1
                else f"截点当日（{trigger.occurred_at}）仅 1 条事件，无同日排序歧义。"
            ),
        },
        {
            "code": "question_future_date_scan",
            "status": "warning" if future_dates else "passed",
            "message": (
                f"自由文本研究问题中出现晚于截点的日期字样（{', '.join(future_dates)}），请人工核查是否存在未来信息预告。"
                if future_dates
                else "自由文本研究问题未检出晚于截点的显式日期。"
            ),
        },
    ]

    if report is None:
        checks = [check for check in checks if check["code"] not in {"evidence_registry_boundary", "opinion_citation_boundary"}]

    return {
        "audit_version": AUDIT_VERSION,
        "passed": len(leaked) == 0,
        "case_id": original_case.case_id,
        "case_version": original_case.version,
        "trigger_event_id": trigger_event_id,
        "cutoff_date": trigger.occurred_at.isoformat(),
        "original_event_count": len(original_case.timeline),
        "allowed_event_count": len(allowed_events),
        "excluded_future_event_count": len(original_case.timeline) - len(allowed_events),
        "original_unplaced_count": len(original_case.unplaced_records),
        "audited_evidence_count": registry_count,
        "audited_opinion_citations": audited_citations,
        "audited_claims": audited_claims,
        "same_day_events_on_cutoff": same_day,
        "future_dates_in_question": future_dates,
        "leaked_count": len(leaked),
        "leaked_items": leaked,
        "checks": checks,
    }
