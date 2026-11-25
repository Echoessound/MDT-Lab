import hashlib
import json
import socket
import sys

import httpx
import pytest

from mdt_demo.research.llm_benchmark import g01_request_plan, run_g01_smoke_suite
from mdt_demo.research.cohort_freeze import manifest_files, prepare_cohort, publish_cohort
from mdt_demo.research.cohort_split import scenario_manifest_lines
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.provider_config import LLMConfigInput
from scripts import run_llm_benchmark
from scripts.run_llm_benchmark import main
from test_research_plan_milestones import _make_llm_config, _public_resolver, _smart_llm_transport


@pytest.mark.parametrize("configured", [False, True])
def test_offline_preflight_without_or_with_configuration(monkeypatch, tmp_path, configured):
    def reject_dns(*args, **kwargs):
        pytest.fail("Preflight must not resolve a provider address")

    monkeypatch.setattr(socket, "getaddrinfo", reject_dns)
    args = ["benchmark", "--mode", "preflight", "--output-dir", str(tmp_path)]
    monkeypatch.delenv("MDT_LLM_API_KEY", raising=False)
    if configured:
        monkeypatch.setenv("MDT_LLM_API_KEY", "local-test-value")
        args.extend(["--base-url", "https://example.com/v1", "--model", "example"])
    monkeypatch.setattr(sys, "argv", args)

    assert main() == (0 if configured else 1)
    contents = (tmp_path / "g01_preflight.json").read_text()
    assert "local-test-value" not in contents
    data = json.loads(contents)
    assert data["configuration_ready"] is configured
    assert {issue["field"] for issue in data["configuration_issues"]} == (
        set() if configured else {"api_key", "base_url", "model"}
    )
    assert data["http_attempts_made"] == 0
    assert data["suite_max_http_attempts"] == 34
    assert len(data["scenarios"]) == 3
    assert not (tmp_path / "g01_smoke_report.json").exists()


def test_bad_preflight_url_does_not_expose_rejected_values(monkeypatch, tmp_path):
    monkeypatch.setenv("MDT_LLM_API_KEY", "sensitive-test-value")
    monkeypatch.setattr(sys, "argv", [
        "benchmark", "--mode", "preflight", "--output-dir", str(tmp_path),
        "--base-url", "https://example.com/v1?key=sensitive-test-value", "--model", "example",
    ])
    assert main() == 1
    contents = (tmp_path / "g01_preflight.json").read_text()
    assert "sensitive-test-value" not in contents
    assert json.loads(contents)["configuration_issues"][0]["field"] == "base_url"


def test_deepseek_smoke_sends_json_contract_on_initial_attempt_and_retry():
    upstream = _smart_llm_transport(fail_first_citation=True)
    requests = []

    def handle(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        assert body["response_format"] == {"type": "json_object"}
        requests.append(body)
        return upstream.handle_request(request)

    config = LLMConfigInput(base_url="https://api.deepseek.com", model="deepseek-flash", api_key="local-fixture")
    report = run_g01_smoke_suite(config, resolver=_public_resolver, transport=httpx.MockTransport(handle))
    assert report["model_config"]["thinking_mode"] == "disabled"
    assert report["model_config"]["response_format_mode"] == "json_object"
    assert report["compatibility"]["all_scenarios_completed"]
    assert report["compatibility"]["validation_totals"]["retry_recovered"] == 1
    assert "connection test" in requests[0]["messages"][0]["content"]
    assert len(requests[2]["messages"]) == 3
    for request in requests[1:]:
        system = request["messages"][0]["content"]
        assert "Example shape" in system and '"required"' in system and '"claims"' in system


def test_preflight_accepts_explicit_local_env_file_without_exposing_key(monkeypatch, tmp_path):
    key_name = "TEST_DEEPSEEK_KEY"
    env_file = tmp_path / ".env"
    env_file.write_text(f"{key_name}=local-file-fixture\n")
    monkeypatch.delenv(key_name, raising=False)
    monkeypatch.setattr(sys, "argv", ["benchmark", "--mode", "preflight", "--api-key-env", key_name,
                                     "--base-url", "https://api.deepseek.com", "--model", "deepseek-flash",
                                     "--env-file", str(env_file), "--output-dir", str(tmp_path)])
    assert main() == 0
    content = (tmp_path / "g01_preflight.json").read_text()
    assert "local-file-fixture" not in content
    assert json.loads(content)["response_format_mode"] == "json_object"


@pytest.mark.parametrize("probe_has_usage", [True, False])
def test_smoke_usage_includes_probe_and_preserves_unknowns(probe_has_usage):
    upstream = _smart_llm_transport(fail_first_citation=True)
    sent = []

    def handle(request):
        result = upstream.handle_request(request)
        sent.append(request)
        if not probe_has_usage and len(sent) == 1:
            body = result.json()
            del body["usage"]
            return httpx.Response(200, json=body)
        return result

    report = run_g01_smoke_suite(
        _make_llm_config(), transport=httpx.MockTransport(handle), resolver=_public_resolver
    )
    assert report["execution_source"] == "injected_transport"
    suite = report["suite_metrics"]
    assert suite["llm_calls"] == len(sent) <= g01_request_plan()["suite_max_http_attempts"]
    assert report["connection_test"]["metrics"]["llm_calls"] == 1
    compat = report["compatibility"]
    assert compat["all_scenarios_completed"]
    assert compat["scenario_retries"] == 1
    assert compat["retry_recovery_rate"] == 1.0
    assert suite["retry_count"] == 1
    assert suite["prompt_tokens"] == (compat["total_prompt_tokens"] + 12 if probe_has_usage else None)
    assert suite["completion_tokens"] == (compat["total_completion_tokens"] + 4 if probe_has_usage else None)
    assert suite["wall_clock_ms"] >= sum(row["metrics"]["wall_clock_ms"] for row in report["scenarios"])


@pytest.mark.parametrize("extra", [
    ["--mode", "paired", "--frozen-cohort", "lock"],
    ["--mode", "smoke", "--frozen-cohort", "lock", "--split-filter", "dev"],
    ["--mode", "paired", "--split-filter", "dev"],
    ["--mode", "paired", "--cohort-input", "input"],
    *[["--mode", "paired", "--frozen-cohort", "lock", "--split-filter", "dev", flag, value]
      for flag, value in (("--source", "seed"), ("--input", "input"), ("--max-cases", "3"), ("--triggers", "latest"))],
])
def test_paired_rejects_ambiguous_selection_before_loading_configuration(monkeypatch, tmp_path, extra, capsys):
    monkeypatch.delenv("MDT_LLM_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["benchmark", "--output-dir", str(tmp_path), *extra])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--frozen-cohort" in capsys.readouterr().err.split("error:")[-1]


def test_frozen_paired_runs_only_manifest_rows_and_reports_denominators(monkeypatch, tmp_path):
    input_path = tmp_path / "cases.json"
    input_path.write_text(json.dumps({"cases": [case.model_dump(mode="json") for case in seed_cases()]}))
    _, manifest, all_rows = prepare_cohort(
        [("research_json", input_path, 3)], trigger_scope="all", dev_ratio=0.3, seed=2026
    )
    rows = [row for row in all_rows if row["split"] == "dev"]
    frozen_dir = tmp_path / "freeze"
    publish_cohort(frozen_dir, manifest_files(manifest, all_rows))
    manifest_bytes = (frozen_dir / "dataset_manifest.json").read_bytes()
    selected = []

    def evaluate(case, trigger, factory, **kwargs):
        selected.append(f"{case.case_id}:v{case.version}:{trigger}")
        return {}

    monkeypatch.setattr(run_llm_benchmark, "evaluate_llm_ablation_matrix", evaluate)
    monkeypatch.setenv("MDT_LLM_API_KEY", "smoke-test-only")
    monkeypatch.setattr(sys, "argv", [
        "benchmark", "--mode", "paired", "--output-dir", str(tmp_path),
        "--base-url", "https://example.com/v1", "--model", "model",
        "--frozen-cohort", str(frozen_dir), "--cohort-input", str(input_path), "--split-filter", "dev",
    ])
    assert main() == 0
    result = json.loads((tmp_path / "llm_paired_results.json").read_text())
    assert selected == [row["scenario_id"] for row in rows] == list(result["matrices"])
    provenance = result["dataset"]
    assert provenance["dataset_manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert provenance["scenario_manifest_sha256"] == manifest["scenario_manifest_sha256"]
    assert provenance["selected_scenario_manifest_sha256"] == hashlib.sha256(
        "".join(scenario_manifest_lines(rows)).encode()
    ).hexdigest()
    assert provenance["selected_family_count"] == manifest["split"]["dev_family_count"]
    assert provenance["selected_scenario_count"] == result["scenario_count"] < len(all_rows)
    for row in rows:
        assert result["matrices"][row["scenario_id"]]["frozen_input_sha256"] == row["frozen_input_sha256"]

    # Even an otherwise equivalent input has a different source-file hash.
    input_path.write_bytes(input_path.read_bytes() + b"\n")
    selected.clear()
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert selected == []
