import pytest

from mdt_demo.disagreement import detect_disagreement
from mdt_demo.schemas import Decision, Role


def opinions_for(agents, case):
    return [agent.initial_review(case) for agent in agents]


def test_unanimous_labels(case, make_agents):
    result = detect_disagreement(opinions_for(make_agents(), case))
    assert not result.has_disagreement
    assert result.sufficient_opinions


def test_conflicting_labels(case, make_agents):
    agents = make_agents([Decision.NEED_MORE_INFORMATION, Decision.READY_FOR_REVIEW, Decision.NEED_MORE_INFORMATION])
    result = detect_disagreement(opinions_for(agents, case))
    assert result.has_disagreement
    assert result.conflicting_agents == list(Role)
    assert set(result.conflicting_decisions) == {Decision.NEED_MORE_INFORMATION, Decision.READY_FOR_REVIEW}


@pytest.mark.parametrize("count", [0, 1, 2])
def test_missing_opinions_never_count_as_consensus(case, make_agents, count):
    result = detect_disagreement(opinions_for(make_agents(), case)[:count])
    assert not result.sufficient_opinions
    assert result.missing_agents


def test_duplicate_roles_do_not_count_as_full_panel(case, make_agents):
    opinions = opinions_for(make_agents(), case)
    result = detect_disagreement([opinions[0], opinions[0], opinions[2]])
    assert not result.sufficient_opinions
