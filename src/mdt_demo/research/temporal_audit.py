"""Independent temporal-boundary leakage auditor (Plan §1 & §6.3).

Reconstructs the legal historical fact whitelist directly from the full source
ResearchCase without calling engine.freeze_context, then verifies case snapshots,
evidence registries, opinion citations, and free-text questions against that whitelist.
"""

from __future__ import annotations

from datetime import date
import re

from .schemas import ResearchCase

AUDIT_VERSION = "temporal-boundary-audit-v1"
ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _independent_whitelist(original_case: ResearchCase, trigger_event_id: str) -> dict:
    trigger = next((e for e in original_case.timeline if e.event_id == trigger_event_id), None)
    if trigger is None:
        raise ValueError(f"触发事件 {trigger_event_id} 不存在于原始病例 {original_case.case_id} v{original_case.version}。")
    cutoff = (trigger.occurred_at, trigger.event_id)
    allowed_events: dict[str, dict] = {}
    allowed_facts: dict[str, tuple[str, object]] = {}
    same_day_ids: list[str] = []
    for event in original_case.timeline:
        if event.occurred_at == trigger.occurred_at:
            same_day_ids.append(event.event_id)
        if (event.occurred_at, event.event_id) <= cutoff:
            allowed_events[event.event_id] = event.model_dump(mode="json")
            for fact_key, value in event.facts.items():
                allowed_facts[f"{event.event_id}:{fact_key}"] = (fact_key, value)
    return {
        "trigger": trigger,
        "cutoff": cutoff,
        "allowed_events": allowed_events,
        "allowed_facts": allowed_facts,
        "same_day_ids": same_day_ids,
    }


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
    return type(left) is type(right) and left == right


def audit_temporal_boundary(original_case: ResearchCase, report: dict) -> dict:
    """Independently audit a run Report against the original full ResearchCase."""
    trigger_event_id = report["trigger_event_id"]
    wl = _independent_whitelist(original_case, trigger_event_id)
    trigger = wl["trigger"]
    allowed_events = wl["allowed_events"]
    allowed_facts = wl["allowed_facts"]
    leaked: list[dict] = []

    snapshot = report.get("case_snapshot") or {}
    snap_timeline = snapshot.get("timeline") or []
    snap_ids = [ev.get("event_id") for ev in snap_timeline]

    # 1. Snapshot timeline check
    for ev in snap_timeline:
        eid = ev.get("event_id")
        if eid not in allowed_events:
            leaked.append({
                "check_code": "snapshot_timeline_boundary",
                "location": "case_snapshot.timeline",
                "item_id": str(eid),
                "detail": "快照包含超出历史截止点或不存在于原版本的事件。",
            })
            continue
        orig = allowed_events[eid]
        if ev.get("occurred_at") != orig["occurred_at"] or ev.get("facts") != orig["facts"]:
            leaked.append({
                "check_code": "snapshot_timeline_boundary",
                "location": f"case_snapshot.timeline[{eid}]",
                "item_id": str(eid),
                "detail": "快照事件的日期或事实内容与原始病例版本不一致。",
            })
    missing_from_snap = [eid for eid in allowed_events if eid not in set(snap_ids)]
    for eid in missing_from_snap:
        leaked.append({
            "check_code": "snapshot_timeline_boundary",
            "location": "case_snapshot.timeline",
            "item_id": eid,
            "detail": "快照缺失截点前的合法历史事件。",
        })

    # 2. Unplaced records check
    unplaced = snapshot.get("unplaced_records") or []
    for rec in unplaced:
        leaked.append({
            "check_code": "unplaced_records_isolated",
            "location": "case_snapshot.unplaced_records",
            "item_id": str(rec.get("record_id", "unknown")),
            "detail": "无可用日期记录（unplaced_records）泄漏进入了历史运行快照。",
        })

    # 3. Evidence registry check
    registry = report.get("evidence_registry") or []
    for ref in registry:
        ev_id = ref.get("evidence_id")
        if ev_id not in allowed_facts:
            leaked.append({
                "check_code": "evidence_registry_boundary",
                "location": "evidence_registry",
                "item_id": str(ev_id),
                "detail": "证据注册表包含截点之外的事实引用。",
            })
        else:
            expected_key, expected_val = allowed_facts[ev_id]
            if ref.get("fact_key") != expected_key or not _same_value(ref.get("value"), expected_val):
                leaked.append({
                    "check_code": "evidence_registry_boundary",
                    "location": f"evidence_registry[{ev_id}]",
                    "item_id": str(ev_id),
                    "detail": "证据注册表中的事实键或值与原病例截点事实不匹配。",
                })

    # 4. Opinion citations & claims check (initial + final + discussion before/after)
    audited_citations = 0
    audited_claims = 0
    opinion_sources: list[tuple[str, dict]] = []
    for idx, op in enumerate(report.get("initial_opinions") or []):
        opinion_sources.append((f"initial_opinions[{idx}]", op))
    for idx, op in enumerate(report.get("final_opinions") or []):
        opinion_sources.append((f"final_opinions[{idx}]", op))
    for idx, rec in enumerate(report.get("discussion_records") or []):
        if rec.get("before"):
            opinion_sources.append((f"discussion_records[{idx}].before", rec["before"]))
        if rec.get("after"):
            opinion_sources.append((f"discussion_records[{idx}].after", rec["after"]))

    for loc, op in opinion_sources:
        for ev_id in op.get("evidence_ids") or []:
            audited_citations += 1
            if ev_id not in allowed_facts:
                leaked.append({
                    "check_code": "opinion_citation_boundary",
                    "location": f"{loc}.evidence_ids",
                    "item_id": str(ev_id),
                    "detail": "专科意见引用了超出历史截止点的证据编号。",
                })
        for claim in op.get("claims") or []:
            audited_claims += 1
            ev_id = claim.get("evidence_id")
            if ev_id not in allowed_facts:
                leaked.append({
                    "check_code": "opinion_citation_boundary",
                    "location": f"{loc}.claims",
                    "item_id": str(ev_id),
                    "detail": "结构化断言引用了截点之外的证据。",
                })
            else:
                expected_key, expected_val = allowed_facts[ev_id]
                if claim.get("fact_key") != expected_key or not _same_value(claim.get("value"), expected_val):
                    leaked.append({
                        "check_code": "opinion_citation_boundary",
                        "location": f"{loc}.claims[{ev_id}]",
                        "item_id": str(ev_id),
                        "detail": "结构化断言的键或值与原始截点事实不一致。",
                    })

    # 5 & 6. Advisory checks: same-day ordering & future dates in free-text question
    same_day = wl["same_day_ids"]
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
                else f"证据注册表全部 {len(registry)} 项事实均与原病例截点事实逐项匹配。"
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
        "audited_evidence_count": len(registry),
        "audited_opinion_citations": audited_citations,
        "audited_claims": audited_claims,
        "same_day_events_on_cutoff": same_day,
        "future_dates_in_question": future_dates,
        "leaked_count": len(leaked),
        "leaked_items": leaked,
        "checks": checks,
    }


def audit_frozen_snapshot(original_case: ResearchCase, frozen: ResearchCase, trigger_event_id: str) -> dict:
    """Audit a frozen ResearchCase context prior to model execution."""
    pseudo_report = {
        "trigger_event_id": trigger_event_id,
        "case_snapshot": frozen.model_dump(mode="json"),
        "evidence_registry": [],
        "initial_opinions": [],
        "final_opinions": [],
        "discussion_records": [],
    }
    return audit_temporal_boundary(original_case, pseudo_report)
