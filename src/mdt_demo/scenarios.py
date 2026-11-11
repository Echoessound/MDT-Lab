"""Explicit test scenarios for the same synthetic fixture, never medical inference."""

from typing import Literal, Sequence

from .agents import OncologyAgent, RadiologyAgent, SurgeryAgent
from .schemas import AgentOpinion, Decision, DisagreementResult, SyntheticCase

Scenario = Literal["standard", "aligned", "partial_failure", "persistent_disagreement"]


class ScenarioSurgeryAgent(SurgeryAgent):
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def initial_review(self, case: SyntheticCase) -> AgentOpinion:
        self._check_case(case)
        if self.scenario == "partial_failure":
            raise RuntimeError("Explicit Mock failure scenario")
        if self.scenario == "aligned":
            return super().discuss(case, [super().initial_review(case)], DisagreementResult(
                has_disagreement=False, sufficient_opinions=True, conflicting_agents=[],
                conflicting_decisions=[], missing_agents=[], discussion_topic="预设一致意见测试",
            ))
        return super().initial_review(case)

    def discuss(
        self, case: SyntheticCase, opinions: Sequence[AgentOpinion], disagreement: DisagreementResult,
    ) -> AgentOpinion:
        if self.scenario == "persistent_disagreement":
            return super().initial_review(case)
        return super().discuss(case, opinions, disagreement)


def mock_agents(scenario: Scenario = "standard"):
    return (OncologyAgent(), ScenarioSurgeryAgent(scenario), RadiologyAgent())
