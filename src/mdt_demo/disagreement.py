"""Compare labels, keeping absence of opinions separate from consensus."""

from collections import Counter
from typing import Sequence

from .schemas import AgentOpinion, DisagreementResult, Role


def detect_disagreement(
    opinions: Sequence[AgentOpinion], expected_agents: Sequence[Role] = tuple(Role),
) -> DisagreementResult:
    counts = Counter(opinion.agent_name for opinion in opinions)
    missing = [name for name in expected_agents if counts[name] != 1]
    sufficient = not missing and set(counts) == set(expected_agents)
    decisions = list(dict.fromkeys(opinion.decision for opinion in opinions))
    conflict = len(decisions) > 1
    return DisagreementResult(
        has_disagreement=conflict, sufficient_opinions=sufficient,
        conflicting_agents=list(dict.fromkeys(opinion.agent_name for opinion in opinions)) if conflict else [],
        conflicting_decisions=decisions if conflict else [], missing_agents=missing,
        discussion_topic=("是否已经具备进入下一步讨论的充分信息？" if conflict else
                          "有效意见不足，不能形成共识。" if not sufficient else
                          "全部参与角色的流程标签一致。"),
    )
