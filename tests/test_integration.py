import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from pydantic import ValidationError

from mdt_demo.config import Settings
from mdt_demo.orchestrator import MDTOrchestrator
from mdt_demo.schemas import AuditEvent, DISCLAIMER, Decision, MDTReport, Stage, SyntheticCase


def read_audit(path):
    return [AuditEvent.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_full_mock_report_and_audit(case, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network access"))
    report = MDTOrchestrator(output_dir=tmp_path).run(case)
    folder = tmp_path / report.run_id
    saved = MDTReport.model_validate_json((folder / "report.json").read_text(encoding="utf-8"))
    assert saved == report
    assert report.status == "completed"
    assert report.final_decision == Decision.NEED_MORE_INFORMATION
    assert report.discussion_triggered and report.discussion_rounds == 1
    assert len(report.initial_opinions) == len(report.final_opinions) == 3
    assert not report.unresolved_disagreements
    assert report.disclaimer == DISCLAIMER
    assert report.missing_information == ["需要确认影像记录的完整性"]
    surgery = next(record for record in report.discussion_records if record.agent_name == "surgery")
    assert surgery.before.decision == Decision.READY_FOR_REVIEW
    assert surgery.after.decision == Decision.NEED_MORE_INFORMATION
    assert surgery.changed
    events = read_audit(folder / "audit.jsonl")
    assert [event.details["current"] for event in events if event.event_type == "state_transition"] == list(Stage)
    assert events[-1].event_type == "run_finished"
    assert all(event.run_id == report.run_id and event.timestamp.tzinfo for event in events)
    ids = {event.event_id for event in events}
    assert set(report.audit_event_ids) <= ids
    assert all(record.audit_event_id in ids for record in report.discussion_records)


def test_consistent_panel_skips_discussion(case, tmp_path, make_agents):
    agents = make_agents()
    report = MDTOrchestrator(agents=agents, output_dir=tmp_path).run(case)
    assert not report.discussion_triggered and report.discussion_rounds == 0
    assert report.discussion_records == []
    assert all(agent.calls == {"initial": 1, "discussion": 0} for agent in agents)


def test_persistent_disagreement_does_not_use_majority_vote(case, tmp_path, make_agents):
    agents = make_agents([Decision.NEED_MORE_INFORMATION, Decision.READY_FOR_REVIEW, Decision.NEED_MORE_INFORMATION])
    report = MDTOrchestrator(agents=agents, output_dir=tmp_path).run(case)
    assert report.final_decision == Decision.DEFER_DECISION
    assert report.unresolved_disagreements
    assert report.discussion_rounds == 1
    assert all(agent.calls == {"initial": 1, "discussion": 1} for agent in agents)


@pytest.mark.parametrize("phase", ["initial", "discussion"])
def test_agent_error_has_no_fabricated_opinion_and_no_secret_leak(case, tmp_path, make_agents, phase):
    agents = make_agents([Decision.NEED_MORE_INFORMATION, Decision.READY_FOR_REVIEW, Decision.NEED_MORE_INFORMATION])
    setattr(agents[1], f"fail_{phase}", True)
    report = MDTOrchestrator(agents=agents, output_dir=tmp_path).run(case)
    assert report.status == "incomplete"
    assert report.final_decision == Decision.DEFER_DECISION
    assert "surgery" not in [opinion.agent_name for opinion in report.final_opinions]
    folder = tmp_path / report.run_id
    events = read_audit(folder / "audit.jsonl")
    assert any(event.event_type == "agent_failed" for event in events)
    for file in folder.iterdir():
        assert "private-api-key-must-not-leak" not in file.read_text(encoding="utf-8")
    if phase == "discussion":
        record = next(record for record in report.discussion_records if record.agent_name == "surgery")
        assert record.status == "failed" and record.after is None
    else:
        assert agents[1].calls == {"initial": 1, "discussion": 0}


@pytest.mark.parametrize("invalid", ["reference", "decision", "role"])
def test_invalid_agent_output_blocks_consensus(case, tmp_path, make_agents, invalid):
    agents = make_agents()
    valid = agents[0].opinion(case, Decision.NEED_MORE_INFORMATION).model_dump()
    if invalid == "reference":
        valid["supporting_event_ids"] = ["FAKE"]
    elif invalid == "decision":
        valid["decision"] = "UNSUPPORTED"
    else:
        valid["agent_name"] = "surgery"
    agents[0].initial_review = lambda case: valid
    report = MDTOrchestrator(agents=agents, output_dir=tmp_path).run(case)
    assert report.status == "incomplete" and report.final_decision == Decision.DEFER_DECISION
    assert len(report.final_opinions) == 2
    assert any("invalid_opinion" in warning for warning in report.warnings)


def test_all_failed_agents_produce_failure_report(case, tmp_path, make_agents):
    agents = make_agents()
    for agent in agents:
        agent.fail_initial = True
    report = MDTOrchestrator(agents=agents, output_dir=tmp_path).run(case)
    assert report.status == "failed" and report.final_decision == Decision.DEFER_DECISION
    assert report.initial_opinions == report.final_opinions == []
    assert not report.discussion_triggered


def test_unsupported_case_produces_explicit_failure(payload, tmp_path):
    payload["patient"]["age"] = 60
    report = MDTOrchestrator(output_dir=tmp_path).run(payload)
    assert report.status == "failed" and report.final_decision == Decision.DEFER_DECISION
    assert any("unsupported_case" in warning for warning in report.warnings)


def test_invalid_case_rejected_before_any_agent_call(payload, tmp_path, make_agents):
    payload["is_synthetic"] = False
    agents = make_agents()
    with pytest.raises(ValidationError):
        MDTOrchestrator(agents=agents, output_dir=tmp_path).run(payload)
    assert all(agent.calls == {"initial": 0, "discussion": 0} for agent in agents)
    assert not list(tmp_path.glob("*/report.json"))
    events = read_audit(next(tmp_path.glob("*/audit.jsonl")))
    assert events[-1].details["status"] == "rejected"


def test_agent_cannot_corrupt_shared_case_or_discussion_snapshot(case, tmp_path, make_agents):
    agents = make_agents([Decision.NEED_MORE_INFORMATION, Decision.READY_FOR_REVIEW, Decision.NEED_MORE_INFORMATION],
                         final=[Decision.NEED_MORE_INFORMATION] * 3)
    original = case.model_dump()
    def initial_with_mutation(local_case):
        opinion = agents[0].opinion(local_case, Decision.NEED_MORE_INFORMATION)
        local_case.timeline.clear()
        return opinion
    def discussion_with_mutation(local_case, opinions, disagreement):
        opinions[1].supporting_event_ids.append("FAKE")
        return agents[0].opinion(local_case, Decision.NEED_MORE_INFORMATION)
    agents[0].initial_review = initial_with_mutation
    agents[0].discuss = discussion_with_mutation
    report = MDTOrchestrator(agents=agents, output_dir=tmp_path).run(case)
    assert case.model_dump() == original
    assert report.status == "completed"
    assert all("FAKE" not in opinion.supporting_event_ids for opinion in report.initial_opinions)


def test_ready_label_with_missing_data_is_not_ready(case, tmp_path, make_agents):
    agents = make_agents([Decision.READY_FOR_REVIEW] * 3)
    original_review = agents[0].initial_review
    agents[0].initial_review = lambda case: original_review(case).model_copy(update={"missing_information": ["资料待核验"]})
    report = MDTOrchestrator(agents=agents, output_dir=tmp_path).run(case)
    assert report.final_decision == Decision.NEED_MORE_INFORMATION


def run_cli(project_root, tmp_path, *args):
    env = {key: value for key, value in os.environ.items() if key not in {"MDT_MODE", "OPENAI_API_KEY"}}
    return subprocess.run(
        [sys.executable, "-m", "mdt_demo", "--case", str(project_root / "data/synthetic_case_001.json"),
         "--output-dir", str(tmp_path / "outputs"), *args],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=15,
    )


def test_default_cli_runs_offline_from_other_directory(project_root, tmp_path):
    result = run_cli(project_root, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Mode: mock" in result.stdout and "Final decision: NEED_MORE_INFORMATION" in result.stdout
    assert len(list((tmp_path / "outputs").glob("*/report.json"))) == 1


def test_cli_invalid_input_is_nonzero(project_root, tmp_path, payload):
    payload["is_synthetic"] = False
    file = tmp_path / "invalid.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    result = run_cli(project_root, tmp_path, "--case", str(file))
    assert result.returncode == 2 and "病例校验失败" in result.stderr


def test_cli_unimplemented_llm_is_explicit(project_root, tmp_path):
    result = run_cli(project_root, tmp_path, "--mode", "llm")
    assert result.returncode == 2 and "尚未实现" in result.stderr
    assert not (tmp_path / "outputs").exists()


def test_cli_malformed_json_is_nonzero(project_root, tmp_path):
    file = tmp_path / "bad.json"
    file.write_text("{", encoding="utf-8")
    result = run_cli(project_root, tmp_path, "--case", str(file))
    assert result.returncode == 2 and "合法的 UTF-8 JSON" in result.stderr


def test_explicit_mode_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MDT_MODE", "llm")
    assert Settings.from_env(mode="mock").mode == "mock"


def test_duplicate_role_configuration_rejected(tmp_path, make_agents):
    agents = make_agents()
    with pytest.raises(ValueError, match="各配置一个"):
        MDTOrchestrator(agents=[agents[0], agents[0], agents[2]], output_dir=tmp_path)
