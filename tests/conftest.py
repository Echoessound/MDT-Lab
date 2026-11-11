import json
from pathlib import Path

import pytest

from mdt_demo.schemas import AgentOpinion, Decision, Role, SyntheticCase


@pytest.fixture
def project_root():
    return Path(__file__).resolve().parents[1]


@pytest.fixture
def payload(project_root):
    return json.loads((project_root / "data/synthetic_case_001.json").read_text(encoding="utf-8"))


@pytest.fixture
def case(payload):
    return SyntheticCase.model_validate(payload)


class ScriptedAgent:
    def __init__(self, name, initial, final=None, fail_initial=False, fail_discussion=False):
        self.name = name
        self.initial = initial
        self.final = final if final is not None else initial
        self.fail_initial = fail_initial
        self.fail_discussion = fail_discussion
        self.calls = {"initial": 0, "discussion": 0}

    def opinion(self, case, decision):
        return AgentOpinion(
            agent_name=self.name, decision=decision, reasoning_summary="测试流程标签",
            supporting_event_ids=[case.timeline[-1].event_id],
            missing_information=[], confidence="low",
        )

    def initial_review(self, case):
        self.calls["initial"] += 1
        if self.fail_initial:
            raise RuntimeError("private-api-key-must-not-leak")
        return self.opinion(case, self.initial)

    def discuss(self, case, opinions, disagreement):
        self.calls["discussion"] += 1
        if self.fail_discussion:
            raise RuntimeError("private-api-key-must-not-leak")
        return self.opinion(case, self.final)


@pytest.fixture
def make_agents():
    def factory(decisions=None, final=None):
        decisions = decisions or [Decision.NEED_MORE_INFORMATION] * 3
        return [ScriptedAgent(role, decisions[index], final[index] if final else None)
                for index, role in enumerate(Role)]
    return factory
