import hashlib
import json
import socket
import sys

import httpx
import pytest

from mdt_demo.research.llm_benchmark import (
    aggregate_usage_meters,
    evaluate_llm_ablation_matrix,
    g01_request_plan,
    run_g01_smoke_suite,
)
from mdt_demo.research.cohort_freeze import manifest_files, prepare_cohort, publish_cohort
from mdt_demo.research.cohort_split import scenario_manifest_lines
from mdt_demo.research.provider import RunLLM
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
    probe_metrics = report["connection_test"]["metrics"]
    assert suite["llm_calls"] == len(sent) <= g01_request_plan()["suite_max_http_attempts"]
    assert probe_metrics["llm_calls"] == 1
    assert probe_metrics["known_prompt_tokens"] == (12 if probe_has_usage else 0)
    assert probe_metrics["known_completion_tokens"] == (4 if probe_has_usage else 0)
    assert probe_metrics["prompt_usage_requests"] == (1 if probe_has_usage else 0)
    assert probe_metrics["completion_usage_requests"] == (1 if probe_has_usage else 0)
    compat = report["compatibility"]
    assert compat["all_scenarios_completed"]
    assert compat["scenario_retries"] == 1
    assert compat["retry_recovery_rate"] == 1.0
    assert suite["retry_count"] == 1
    assert suite["prompt_tokens"] == (compat["total_prompt_tokens"] + 12 if probe_has_usage else None)
    assert suite["completion_tokens"] == (compat["total_completion_tokens"] + 4 if probe_has_usage else None)
    assert suite["known_prompt_tokens"] == compat["total_prompt_tokens"] + (12 if probe_has_usage else 0)
    assert suite["known_completion_tokens"] == compat["total_completion_tokens"] + (4 if probe_has_usage else 0)
    assert suite["prompt_usage_requests"] == suite["llm_calls"] - (0 if probe_has_usage else 1)
    assert suite["completion_usage_requests"] == suite["llm_calls"] - (0 if probe_has_usage else 1)
    assert suite["wall_clock_ms"] >= sum(row["metrics"]["wall_clock_ms"] for row in report["scenarios"])


def test_smoke_suite_retains_known_subtotals_and_request_counts_across_partial_usage():
    upstream = _smart_llm_transport(fail_first_citation=True)
    sent = []

    def handle(request):
        sent.append(request)
        attempt_idx = len(sent)
        if attempt_idx == 1:
            return httpx.Response(503, text="probe-upstream-secret-503")
        if attempt_idx == 5:
            raise httpx.ReadTimeout("scenario-timeout-secret", request=request)
        result = upstream.handle_request(request)
        if attempt_idx == 7:
            body = result.json()
            body["usage"] = {
                "prompt_tokens": 120,
                "completion_tokens": "bad-str",
                "raw_debug": "leak-usage-string",
            }
            return httpx.Response(200, json=body)
        if attempt_idx == 8:
            body = result.json()
            del body["usage"]
            return httpx.Response(200, json=body)
        return result

    report = run_g01_smoke_suite(
        _make_llm_config(), transport=httpx.MockTransport(handle), resolver=_public_resolver
    )
    probe = report["connection_test"]
    assert probe["ok"] is True
    assert probe["metrics"] == {
        "llm_calls": 2,
        "retry_count": 1,
        "prompt_tokens": None,
        "completion_tokens": None,
        "known_prompt_tokens": 12,
        "known_completion_tokens": 4,
        "prompt_usage_requests": 1,
        "completion_usage_requests": 1,
    }
    compat = report["compatibility"]
    assert compat["all_scenarios_completed"] is True
    assert compat["usage_reported_complete"] is False
    assert compat["total_prompt_tokens"] is None
    assert compat["total_completion_tokens"] is None

    suite = report["suite_metrics"]
    meters = [probe["metrics"], *(row["metrics"] for row in report["scenarios"])]
    assert suite["llm_calls"] == len(sent)
    assert suite["retry_count"] == 1 + compat["scenario_retries"] == 3
    assert suite["prompt_tokens"] is None
    assert suite["completion_tokens"] is None
    assert suite["prompt_usage_requests"] == len(sent) - 3
    assert suite["completion_usage_requests"] == len(sent) - 4
    assert suite["known_prompt_tokens"] == 12 + 100 + 120 * (suite["prompt_usage_requests"] - 2)
    assert suite["known_completion_tokens"] == 4 + 50 + 45 * (suite["completion_usage_requests"] - 2)
    for key in ("known_prompt_tokens", "known_completion_tokens", "prompt_usage_requests", "completion_usage_requests"):
        assert suite[key] == sum(meter[key] for meter in meters)

    serialized = json.dumps(report, ensure_ascii=False)
    for forbidden in (
        "sk-secret-do-not-leak",
        "probe-upstream-secret-503",
        "scenario-timeout-secret",
        "bad-str",
        "leak-usage-string",
    ):
        assert forbidden not in serialized


def test_cli_smoke_writes_known_usage_subtotals_without_secrets(monkeypatch, tmp_path, capsys):
    upstream = _smart_llm_transport(fail_first_citation=True)
    calls = []

    def handle(request):
        calls.append(request)
        result = upstream.handle_request(request)
        if len(calls) == 1:
            body = result.json()
            del body["usage"]
            return httpx.Response(200, json=body)
        return result

    real_smoke = run_g01_smoke_suite
    monkeypatch.setattr(
        run_llm_benchmark,
        "run_g01_smoke_suite",
        lambda config, **kwargs: real_smoke(
            config,
            transport=httpx.MockTransport(handle),
            resolver=_public_resolver,
            **{k: v for k, v in kwargs.items() if k not in {"transport", "resolver"}},
        ),
    )
    monkeypatch.setenv("MDT_LLM_API_KEY", "cli-fixture-secret")
    monkeypatch.setattr(sys, "argv", [
        "benchmark", "--mode", "smoke", "--base-url", "https://example.com/v1", "--model", "example",
        "--sleep-seconds", "0", "--output-dir", str(tmp_path),
    ])

    assert main() == 0
    stdout = capsys.readouterr().out
    report_text = (tmp_path / "g01_smoke_report.json").read_text(encoding="utf-8")
    assert "cli-fixture-secret" not in stdout
    assert "cli-fixture-secret" not in report_text
    report = json.loads(report_text)
    suite = report["suite_metrics"]
    assert suite["prompt_tokens"] is None and suite["completion_tokens"] is None
    assert suite["known_prompt_tokens"] == report["compatibility"]["total_prompt_tokens"]
    assert suite["known_completion_tokens"] == report["compatibility"]["total_completion_tokens"]
    assert suite["prompt_usage_requests"] == suite["llm_calls"] - 1
    assert suite["completion_usage_requests"] == suite["llm_calls"] - 1
    assert f"已知Token(输入/输出)={suite['known_prompt_tokens']}({suite['prompt_usage_requests']}/{suite['llm_calls']})/{suite['known_completion_tokens']}({suite['completion_usage_requests']}/{suite['llm_calls']})" in stdout


def test_smoke_one_sided_missing_usage_keeps_complete_side_in_compatibility_and_suite():
    upstream = _smart_llm_transport()
    sent = []

    def handle(request):
        sent.append(request)
        result = upstream.handle_request(request)
        if len(sent) == 2:
            body = result.json()
            del body["usage"]["completion_tokens"]
            return httpx.Response(200, json=body)
        return result

    report = run_g01_smoke_suite(
        _make_llm_config(), transport=httpx.MockTransport(handle), resolver=_public_resolver
    )
    compat = report["compatibility"]
    suite = report["suite_metrics"]
    assert compat["usage_reported_complete"] is False
    assert compat["total_prompt_tokens"] is not None
    assert compat["total_completion_tokens"] is None
    assert suite["prompt_tokens"] == compat["total_prompt_tokens"] + 12 == suite["known_prompt_tokens"]
    assert suite["completion_tokens"] is None
    assert suite["prompt_usage_requests"] == suite["llm_calls"]
    assert suite["completion_usage_requests"] == suite["llm_calls"] - 1


def test_smoke_retains_known_usage_when_connection_test_and_scenario_fail():
    upstream = _smart_llm_transport()
    sent = []

    def handle(request):
        sent.append(request)
        idx = len(sent)
        if idx == 1:
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"ok": False})}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 3},
            })
        if idx == 2:
            return httpx.Response(503, text="probe-503-secret")
        if idx == 4:
            body = upstream.handle_request(request).json()
            msg = json.loads(body["choices"][0]["message"]["content"])
            msg["agent_id"] = "surgery"
            body["choices"][0]["message"]["content"] = json.dumps(msg, ensure_ascii=False)
            body["usage"] = {"prompt_tokens": 80, "completion_tokens": 25}
            return httpx.Response(200, json=body)
        if idx == 5:
            raise httpx.ReadTimeout("scenario-timeout-secret", request=request)
        return upstream.handle_request(request)

    report = run_g01_smoke_suite(
        _make_llm_config(), transport=httpx.MockTransport(handle), resolver=_public_resolver
    )
    probe = report["connection_test"]
    assert probe["ok"] is False
    assert probe["error_code"] == "LLM_PROVIDER_ERROR"
    assert probe["metrics"] == {
        "llm_calls": 2,
        "retry_count": 1,
        "prompt_tokens": None,
        "completion_tokens": None,
        "known_prompt_tokens": 9,
        "known_completion_tokens": 3,
        "prompt_usage_requests": 1,
        "completion_usage_requests": 1,
    }
    assert report["scenarios"][0]["status"] == "incomplete"
    suite = report["suite_metrics"]
    meters = [probe["metrics"], *(row["metrics"] for row in report["scenarios"])]
    assert suite["prompt_tokens"] is None and suite["completion_tokens"] is None
    assert suite["llm_calls"] == len(sent)
    for key in ("known_prompt_tokens", "known_completion_tokens", "prompt_usage_requests", "completion_usage_requests"):
        assert suite[key] == sum(meter[key] for meter in meters)
    serialized = json.dumps(report, ensure_ascii=False)
    assert "probe-503-secret" not in serialized and "scenario-timeout-secret" not in serialized


def test_paired_matrix_and_cli_aggregate_known_usage_without_double_counting_b2_b3(monkeypatch, tmp_path, capsys):
    upstream = _smart_llm_transport()
    calls = []

    def handle(request):
        calls.append(request)
        result = upstream.handle_request(request)
        if len(calls) == 2:
            body = result.json()
            del body["usage"]
            return httpx.Response(200, json=body)
        return result

    config = _make_llm_config()
    matrix = evaluate_llm_ablation_matrix(
        seed_cases()[0],
        "E002",
        lambda: RunLLM(config, transport=httpx.MockTransport(handle), resolver=_public_resolver),
    )
    suite = matrix["suite_metrics"]
    methods = {row["method_id"]: row for row in matrix["methods"]}
    unique_rows = [methods[mid] for mid in ("B0", "B1", "B3", "A1", "A3", "A4")]
    expected = aggregate_usage_meters(unique_rows)
    for key, value in expected.items():
        assert suite[key] == value
    assert suite["llm_calls"] == len(calls)
    assert suite["prompt_tokens"] is None and suite["completion_tokens"] is None
    assert suite["prompt_usage_requests"] == len(calls) - 1
    assert suite["completion_usage_requests"] == len(calls) - 1

    cli_calls = []

    def cli_handle(request):
        cli_calls.append(request)
        result = upstream.handle_request(request)
        if len(cli_calls) == 1:
            body = result.json()
            del body["usage"]
            return httpx.Response(200, json=body)
        return result

    monkeypatch.setattr(
        run_llm_benchmark,
        "RunLLM",
        lambda cfg, **kwargs: RunLLM(
            cfg,
            transport=httpx.MockTransport(cli_handle),
            resolver=_public_resolver,
            response_format_mode=kwargs.get("response_format_mode"),
        ),
    )
    monkeypatch.setenv("MDT_LLM_API_KEY", "paired-fixture-secret")
    monkeypatch.setattr(sys, "argv", [
        "benchmark", "--mode", "paired", "--source", "seed", "--max-cases", "1", "--triggers", "latest",
        "--base-url", "https://example.com/v1", "--model", "example",
        "--sleep-seconds", "0", "--output-dir", str(tmp_path),
    ])
    assert main() == 0
    stdout = capsys.readouterr().out
    report_text = (tmp_path / "llm_paired_results.json").read_text(encoding="utf-8")
    assert "paired-fixture-secret" not in stdout and "paired-fixture-secret" not in report_text
    paired_report = json.loads(report_text)
    cli_suite = paired_report["suite_metrics"]
    assert cli_suite["llm_calls"] == len(cli_calls)
    assert cli_suite["prompt_tokens"] is None and cli_suite["completion_tokens"] is None
    assert cli_suite["prompt_usage_requests"] == len(cli_calls) - 1
    assert cli_suite["completion_usage_requests"] == len(cli_calls) - 1
    assert f"已知Token(输入/输出)={cli_suite['known_prompt_tokens']}({cli_suite['prompt_usage_requests']}/{cli_suite['llm_calls']})/{cli_suite['known_completion_tokens']}({cli_suite['completion_usage_requests']}/{cli_suite['llm_calls']})" in stdout


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
