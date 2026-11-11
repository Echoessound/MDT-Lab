"""Conservative final-label policy. No voting or generated medical conclusions."""

from .disagreement import detect_disagreement
from .schemas import (
    AgentOpinion, Decision, DiscussionRecord, MDTReport, Mode, Role, SyntheticCase,
)


def build_report(
    *, run_id: str, case: SyntheticCase, case_sha256: str, mode: Mode,
    initial_opinions: list[AgentOpinion], final_opinions: list[AgentOpinion],
    discussion_records: list[DiscussionRecord], discussion_triggered: bool,
    errors: list[str], audit_event_ids: list[str],
) -> MDTReport:
    disagreement = detect_disagreement(final_opinions)
    missing = list(dict.fromkeys(
        item for opinion in final_opinions for item in opinion.missing_information
    ))
    warnings = list(errors)
    if mode == Mode.MOCK:
        warnings.append("Mock 意见为预设流程演示，不代表真实医学推理。")
    unresolved = [disagreement] if disagreement.has_disagreement else []
    if unresolved:
        warnings.append("一轮讨论后仍有分歧，保留不同意见并暂缓决策。")
    if not disagreement.sufficient_opinions:
        warnings.append("未获得全部三个角色的有效最终意见，不能宣称共识。")
        missing.extend(f"需要 {role.value} 的有效意见" for role in disagreement.missing_agents)

    # A failure in either stage remains blocking; a surviving majority is insufficient.
    if errors or not disagreement.sufficient_opinions or unresolved:
        decision = Decision.DEFER_DECISION
    else:
        decision = final_opinions[0].decision
        if decision == Decision.READY_FOR_REVIEW and missing:
            decision = (Decision.NEED_MORE_INFORMATION
                        if Decision.NEED_MORE_INFORMATION in case.available_options
                        else Decision.DEFER_DECISION)
            warnings.append("意见列出了待补资料，不能将资料状态标记为已就绪。")

    status = "completed"
    if errors or len(final_opinions) != len(Role):
        status = "incomplete" if final_opinions else "failed"
    return MDTReport(
        run_id=run_id, case_id=case.case_id, mode=mode, status=status,
        initial_opinions=initial_opinions,
        discussion_triggered=discussion_triggered,
        discussion_rounds=int(discussion_triggered), discussion_records=discussion_records,
        final_opinions=final_opinions, final_decision=decision,
        unresolved_disagreements=unresolved,
        missing_information=list(dict.fromkeys(missing)), warnings=warnings,
        case_sha256=case_sha256, audit_event_ids=audit_event_ids,
    )
