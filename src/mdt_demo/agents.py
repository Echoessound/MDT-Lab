"""Three role-isolated Mock agents, strictly scoped to the supplied fixture."""

from typing import Protocol, Sequence

from .schemas import AgentOpinion, Decision, DisagreementResult, Role, SyntheticCase


class Agent(Protocol):
    name: Role

    def initial_review(self, case: SyntheticCase) -> AgentOpinion: ...

    def discuss(
        self, case: SyntheticCase, opinions: Sequence[AgentOpinion],
        disagreement: DisagreementResult,
    ) -> AgentOpinion: ...


class UnsupportedCaseError(ValueError):
    """This deterministic script does not cover the supplied synthetic scenario."""


def demo_case() -> SyntheticCase:
    """The exact scenario supported by V0.1, independent of the working directory."""
    return SyntheticCase.model_validate({
        "case_id": "SYN-001", "is_synthetic": True,
        "patient": {"age": 58, "sex": "female"},
        "timeline": [
            {"event_id": "E001", "date": "2026-01-05", "type": "initial_assessment",
             "description": "模拟病例：发现需要进一步评估的异常影像表现。"},
            {"event_id": "E002", "date": "2026-01-12", "type": "imaging",
             "description": "模拟病例：部分关键影像信息尚未完成核验。"},
        ],
        "current_question": "当前模拟病例是否具备进入下一步决策讨论的充分信息？",
        "available_options": list(Decision),
    })


class MockAgent:
    name: Role

    def _check_case(self, case: SyntheticCase) -> None:
        if case != demo_case():
            raise UnsupportedCaseError("Mock 仅支持随项目提供的完整 SYN-001 模拟场景")

    def initial_review(self, case: SyntheticCase) -> AgentOpinion:
        self._check_case(case)
        is_surgery = self.name == Role.SURGERY
        return AgentOpinion(
            agent_name=self.name,
            decision=Decision.READY_FOR_REVIEW if is_surgery else Decision.NEED_MORE_INFORMATION,
            reasoning_summary=(
                "预设 Mock 流程标签（非医学推理）：外科角色暂认为可进入资料复核，供分歧流程演示。"
                if is_surgery else
                "预设 Mock 流程标签（非医学推理）：E002 明示部分影像信息尚未核验。"
            ),
            supporting_event_ids=["E002"],
            missing_information=[] if is_surgery else ["需要确认影像记录的完整性"],
            confidence="low",
        )

    def discuss(
        self, case: SyntheticCase, opinions: Sequence[AgentOpinion],
        disagreement: DisagreementResult,
    ) -> AgentOpinion:
        self._check_case(case)
        own = next(opinion for opinion in opinions if opinion.agent_name == self.name)
        if self.name != Role.SURGERY:
            return own.model_copy(deep=True)
        return AgentOpinion(
            agent_name=self.name, decision=Decision.NEED_MORE_INFORMATION,
            reasoning_summary="预设 Mock 讨论更新：根据 E002 的未核验信息，先补齐资料再讨论。",
            supporting_event_ids=["E002"],
            missing_information=["需要确认影像记录的完整性"], confidence="low",
        )


class OncologyAgent(MockAgent):
    name = Role.ONCOLOGY


class SurgeryAgent(MockAgent):
    name = Role.SURGERY


class RadiologyAgent(MockAgent):
    name = Role.RADIOLOGY
