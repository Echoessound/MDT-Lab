"""Provider verification uses a local HTTP transport stub; no paid API requests."""

import json

import httpx
import pytest
from pydantic import ValidationError

from mdt_demo.research.provider import LLMConfigInput, ProviderError, SettingsService


def config(**updates):
    return {"provider": "openai-compatible", "base_url": "https://api.example.test/v1",
            "model": "fixture-model", "api_key": "fixture-secret-never-return",
            "timeout_seconds": 1, "temperature": 0, "max_output_tokens": 300, **updates}


def context():
    return {"run_id": "run_fixture", "case_id": "SYN-TEST", "case_version": 1,
            "agent_id": "oncology", "phase": "initial", "current_question": "资料是否完整？",
            "evidence_registry": [{"evidence_id": "E001:imaging_complete", "event_id": "E001",
                                   "fact_key": "imaging_complete", "value": True}],
            "current_facts": {"imaging_complete": True}, "events": [], "trigger_event": {},
            "required_fields": ["imaging_complete"], "missing_information": [],
            "prior_opinion": None, "peer_opinions": [], "conflicts": []}


def output(**updates):
    return {"agent_id": "oncology", "decision": "READY_FOR_REVIEW", "summary": "合成影像记录已齐备。",
            "evidence_ids": ["E001:imaging_complete"],
            "claims": [{"fact_key": "imaging_complete", "value": True, "evidence_id": "E001:imaging_complete"}],
            "missing_information": [], "confidence": "medium", **updates}


def response(data=None, *, usage=True):
    body = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data or output())}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 21, "completion_tokens": 13}
    return httpx.Response(200, json=body)


def settings(handler, resolver=lambda _: ["93.184.216.34"]):
    service = SettingsService(transport=httpx.MockTransport(handler), resolver=resolver)
    service.configure(config())
    return service


def test_configuration_never_returns_secret_and_run_keeps_frozen_config():
    captured = []

    def handler(request):
        captured.append((request.headers["authorization"], json.loads(request.content)["model"]))
        return response()

    service = settings(handler)
    frozen = service.make_generator()
    public = service.configure(config(model="updated-model", api_key="replacement-secret"))
    assert public["has_api_key"] and public["configured"]
    assert "api_key" not in {key for key in public if key != "has_api_key"}
    assert "replacement-secret" not in json.dumps(public)
    service.clear()
    assert not service.status()["has_api_key"]
    frozen(context())
    assert captured == [("Bearer fixture-secret-never-return", "fixture-model")]
    with pytest.raises(ProviderError, match="LLM_NOT_CONFIGURED"):
        service.make_generator()


def test_changing_endpoint_cannot_reuse_existing_secret():
    service = settings(lambda _: response())
    same = service.configure(config(api_key="", model="second-model"))
    assert same["model"] == "second-model"
    with pytest.raises(ProviderError, match="LLM_KEY_REQUIRED"):
        service.configure(config(base_url="https://other.example.test/v1", api_key=""))


@pytest.mark.parametrize("url", ["http://example.com/v1", "https://127.0.0.1/v1", "https://localhost/v1",
                                  "https://169.254.169.254/", "https://192.168.1.2/", "https://example.com/?key=secret",
                                  "https://user:pass@example.com/v1", "https://service.internal/v1"])
def test_configuration_rejects_unsafe_service_urls(url):
    with pytest.raises(ValidationError):
        LLMConfigInput.model_validate(config(base_url=url))


def test_private_dns_resolution_stops_before_sending_credentials():
    called = []
    service = settings(lambda request: called.append(request) or response(), resolver=lambda _: ["127.0.0.1"])
    with pytest.raises(ProviderError, match="LLM_PRIVATE_DESTINATION"):
        service.make_generator()(context())
    assert called == []


def test_valid_response_uses_strict_schema_and_reports_actual_usage():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response()

    generator = settings(handler).make_generator()
    result = generator(context())
    assert result["model_info"]["prompt_tokens"] == 21
    assert result["model_info"]["attempts"] == 1
    assert generator.metrics == {"llm_calls": 1, "retry_count": 0, "prompt_tokens": 21, "completion_tokens": 13}
    assert requests[0]["response_format"]["json_schema"]["strict"] is True
    assert requests[0]["response_format"]["json_schema"]["schema"]["additionalProperties"] is False


@pytest.mark.parametrize("bad", [
    output(agent_id="surgery"),
    output(evidence_ids=["FUTURE:imaging_complete"], claims=[{"fact_key": "imaging_complete", "value": True, "evidence_id": "FUTURE:imaging_complete"}]),
    output(claims=[{"fact_key": "imaging_complete", "value": False, "evidence_id": "E001:imaging_complete"}]),
    output(claims=[{"fact_key": "imaging_complete", "value": 1, "evidence_id": "E001:imaging_complete"}]),
])
def test_invalid_role_or_evidence_gets_only_one_correction_retry(bad):
    calls = []

    def handler(request):
        calls.append(request)
        return response(bad if len(calls) == 1 else output())

    generator = settings(handler).make_generator()
    result = generator(context())
    assert len(calls) == 2 and result["model_info"]["attempts"] == 2
    assert generator.metrics["retry_count"] == 1
    assert generator.metrics["prompt_tokens"] == 42
    assert "previous response failed" in json.loads(calls[1].content)["messages"][-1]["content"]


def test_repeated_invalid_output_is_failure_not_mock_fallback():
    generator = settings(lambda _: response(output(agent_id="surgery"))).make_generator()
    with pytest.raises(ProviderError, match="LLM_INVALID_OUTPUT") as error:
        generator(context())
    assert error.value.attempts == 2 and generator.metrics["llm_calls"] == 2


@pytest.mark.parametrize("status,expected_calls,code", [
    (401, 1, "LLM_AUTHENTICATION_ERROR"), (403, 1, "LLM_AUTHENTICATION_ERROR"),
    (400, 1, "LLM_REQUEST_REJECTED"), (302, 1, "LLM_REQUEST_REJECTED"),
    (429, 2, "LLM_RATE_LIMIT"), (503, 2, "LLM_PROVIDER_ERROR"),
])
def test_upstream_errors_are_bounded_and_redacted(status, expected_calls, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-upstream-debug-and-fixture-secret", headers={"Location": "https://elsewhere.example/"})

    generator = settings(handler).make_generator()
    with pytest.raises(ProviderError) as result:
        generator(context())
    assert result.value.code == code and len(calls) == expected_calls
    assert "private-upstream" not in result.value.message
    assert generator.metrics["prompt_tokens"] is None


def test_timeout_has_one_retry_and_no_raw_exception():
    def handler(request):
        raise httpx.ReadTimeout("secret-key-in-private-debug", request=request)

    generator = settings(handler).make_generator()
    with pytest.raises(ProviderError) as result:
        generator(context())
    assert result.value.code == "LLM_TIMEOUT"
    assert generator.metrics["llm_calls"] == 2 and generator.metrics["retry_count"] == 1
    assert "secret" not in result.value.message


def test_absent_token_usage_is_unknown_not_zero():
    generator = settings(lambda _: response(usage=False)).make_generator()
    result = generator(context())
    assert result["model_info"]["prompt_tokens"] is None
    assert generator.metrics["completion_tokens"] is None


def test_connection_test_contains_no_case_data():
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        return response({"ok": True})

    result = settings(handler).test()
    assert result["ok"] is True
    assert "evidence_registry" not in json.dumps(captured)
    assert "case_id" not in json.dumps(captured)


def test_partial_usage_preserves_unknown_totals_while_keeping_known_subtotals():
    calls = []

    def recover_after_503(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, text="private-503-body-fixture-secret")
        return response()

    generator = settings(recover_after_503).make_generator()
    result = generator(context())
    assert result["model_info"]["attempts"] == 2
    assert result["model_info"]["prompt_tokens"] is None
    assert result["model_info"]["completion_tokens"] is None
    assert generator.metrics == {"llm_calls": 2, "retry_count": 1, "prompt_tokens": None, "completion_tokens": None}
    assert generator.usage_summary() == {
        "known_prompt_tokens": 21,
        "known_completion_tokens": 13,
        "prompt_usage_requests": 1,
        "completion_usage_requests": 1,
    }

    timeout_calls = []

    def timeout_after_invalid(request):
        timeout_calls.append(request)
        if len(timeout_calls) == 1:
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output(agent_id="surgery"))}}],
                "usage": {"prompt_tokens": 19, "completion_tokens": 7},
            })
        raise httpx.ReadTimeout("timeout-debug-fixture-secret", request=request)

    failing = settings(timeout_after_invalid).make_generator()
    with pytest.raises(ProviderError, match="LLM_TIMEOUT"):
        failing(context())
    assert failing.metrics == {"llm_calls": 2, "retry_count": 1, "prompt_tokens": None, "completion_tokens": None}
    assert failing.usage_summary() == {
        "known_prompt_tokens": 19,
        "known_completion_tokens": 7,
        "prompt_usage_requests": 1,
        "completion_usage_requests": 1,
    }


def test_one_sided_and_invalid_usage_fields_are_counted_independently_and_sanitized():
    payloads = [
        {"prompt_tokens": 30, "completion_tokens": True, "debug_secret": "raw-token-leak"},
        {"prompt_tokens": -1, "completion_tokens": 15, "extra": "leak-extra-field"},
        {"prompt_tokens": "40", "completion_tokens": 12.5},
    ]

    def handler(_request):
        usage = payloads.pop(0)
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output())}}],
            "usage": usage,
        })

    generator = settings(handler).make_generator()
    r1 = generator(context())
    r2 = generator(context())
    r3 = generator(context())
    assert r1["model_info"]["prompt_tokens"] == 30 and r1["model_info"]["completion_tokens"] is None
    assert r2["model_info"]["prompt_tokens"] is None and r2["model_info"]["completion_tokens"] == 15
    assert r3["model_info"]["prompt_tokens"] is None and r3["model_info"]["completion_tokens"] is None
    assert generator.metrics == {"llm_calls": 3, "retry_count": 0, "prompt_tokens": None, "completion_tokens": None}
    assert generator.usage_summary() == {
        "known_prompt_tokens": 30,
        "known_completion_tokens": 15,
        "prompt_usage_requests": 1,
        "completion_usage_requests": 1,
    }
    dumped = json.dumps({"results": [r1, r2, r3], "summary": generator.usage_summary()})
    assert "raw-token-leak" not in dumped and "leak-extra-field" not in dumped


def test_malformed_http_200_choices_trigger_bounded_retry_and_preserve_usage():
    recovered_calls = []

    def recover_after_null_message(_request):
        recovered_calls.append(1)
        if len(recovered_calls) == 1:
            return httpx.Response(200, json={
                "choices": [{"message": None}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            })
        return response()

    generator = settings(recover_after_null_message).make_generator()
    result = generator(context())
    assert result["model_info"]["attempts"] == 2
    assert result["model_info"]["prompt_tokens"] == 32
    assert result["model_info"]["completion_tokens"] == 16
    assert generator.usage_summary() == {
        "known_prompt_tokens": 32,
        "known_completion_tokens": 16,
        "prompt_usage_requests": 2,
        "completion_usage_requests": 2,
    }

    bad_payloads = [
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2}},
        {"choices": [{"message": {"content": None}}], "usage": {"prompt_tokens": 14}},
    ]
    failing = settings(lambda _req: httpx.Response(200, json=bad_payloads.pop(0))).make_generator()
    with pytest.raises(ProviderError, match="LLM_INVALID_OUTPUT"):
        failing(context())
    assert failing.validation_telemetry["first_attempt_schema_failures"] == 1
    assert failing.metrics == {"llm_calls": 2, "retry_count": 1, "prompt_tokens": 24, "completion_tokens": None}
    assert failing.usage_summary() == {
        "known_prompt_tokens": 24,
        "known_completion_tokens": 2,
        "prompt_usage_requests": 2,
        "completion_usage_requests": 1,
    }
