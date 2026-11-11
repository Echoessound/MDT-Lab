import socket

import pytest

from mdt_demo.agents import OncologyAgent, RadiologyAgent, SurgeryAgent, UnsupportedCaseError, demo_case
from mdt_demo.disagreement import detect_disagreement
from mdt_demo.schemas import Decision, SyntheticCase


def test_fixture_matches_documented_supported_case(case):
    assert case == demo_case()


def test_initial_and_discussion_opinions_are_deterministic(case, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Mock must not access network")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", no_network)
    agents = [OncologyAgent(), SurgeryAgent(), RadiologyAgent()]
    initial = [agent.initial_review(case) for agent in agents]
    assert [opinion.decision for opinion in initial] == [
        Decision.NEED_MORE_INFORMATION, Decision.READY_FOR_REVIEW, Decision.NEED_MORE_INFORMATION,
    ]
    assert initial == [agent.initial_review(case) for agent in agents]
    conflict = detect_disagreement(initial)
    final = [agent.discuss(case, initial, conflict) for agent in agents]
    assert all(opinion.decision == Decision.NEED_MORE_INFORMATION for opinion in final)
    assert final[0] == initial[0] and final[2] == initial[2]
    assert initial[1].decision == Decision.READY_FOR_REVIEW


@pytest.mark.parametrize("agent_type", [OncologyAgent, SurgeryAgent, RadiologyAgent])
def test_changed_facts_with_same_id_are_unsupported(payload, agent_type):
    payload["timeline"][1]["description"] = "完全不同的虚构场景"
    changed = SyntheticCase.model_validate(payload)
    with pytest.raises(UnsupportedCaseError):
        agent_type().initial_review(changed)
