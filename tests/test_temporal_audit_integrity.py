"""A stored report must be independently traceable to the selected source version."""

import pytest

from mdt_demo.research import engine, llm_benchmark
from mdt_demo.research.engine import execute, freeze_context
from mdt_demo.research.provider import RunLLM
from mdt_demo.research.schemas import ResearchCase, RunRequest
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.temporal_audit import audit_frozen_snapshot, audit_temporal_boundary
from test_research_plan_milestones import _make_llm_config, _public_resolver, _smart_llm_transport


@pytest.fixture
def run():
    data = seed_cases()[0].model_dump(mode="json")
    data["provenance"][0]["artifact_sha256"] = "1" * 64
    data["timeline"][1].update(source_record_locator="sheet:row=2",
                               source_fields={"imaging_complete": "Imaging"})
    case = ResearchCase.model_validate(data)
    request = RunRequest(case_id=case.case_id, case_version=1, trigger_event_id="E002")
    return case, execute(case, request, "audit_refs", lambda *args: None, lambda: False)


def test_pre_execution_snapshot_has_no_registry_but_a_report_requires_one(run):
    case, report = run
    audit = audit_frozen_snapshot(case, freeze_context(case, "E002"), "E002")
    assert audit["passed"] and audit["audited_evidence_count"] == 0
    assert "evidence_registry_boundary" not in {check["code"] for check in audit["checks"]}
    assert audit_temporal_boundary(case, report)["passed"]
    report["evidence_registry"].clear()
    assert not audit_temporal_boundary(case, report)["passed"]


@pytest.mark.parametrize("change", ["omit", "repeat", "malformed", "event_id", "dataset_version",
                                     "source_name", "source_record_id", "artifact_sha256",
                                     "source_record_locator", "source_field", "quote_or_fact", "value"])
def test_registry_rows_are_complete_unique_and_match_source_provenance(run, change):
    case, report = run
    rows = report["evidence_registry"]
    ref = next(row for row in rows if row["evidence_id"] == "E002:imaging_complete")
    if change == "omit":
        rows.remove(ref)
    elif change == "repeat":
        rows.append(ref)
    elif change == "malformed":
        ref["evidence_id"] = {}
    else:
        ref[change] = 1 if change == "value" else "changed"
    issues = audit_temporal_boundary(case, report)["leaked_items"]
    assert issues and all(item["check_code"] == "evidence_registry_boundary" for item in issues)


@pytest.mark.parametrize("section", ["initial_opinions", "final_opinions", "before", "after"])
def test_every_copy_of_an_opinion_reference_is_independently_checked(run, section):
    case, report = run
    op = (report[section][0] if section.endswith("_opinions")
          else report["discussion_records"][0][section])
    op["evidence_refs"][0]["source_field"] = "changed"
    issues = audit_temporal_boundary(case, report)["leaked_items"]
    assert issues
    assert all(item["check_code"] == "opinion_citation_boundary" and "evidence_refs" in item["location"]
               for item in issues)


@pytest.mark.parametrize("change", ["duplicate", "omit", "undeclared", "undeclared_claim"])
def test_declared_citations_bind_the_opinion_references_and_claims(run, change):
    case, report = run
    op = report["final_opinions"][0]
    other = next(row for row in report["evidence_registry"] if row["evidence_id"] not in op["evidence_ids"])
    if change == "duplicate":
        op["evidence_refs"].append(op["evidence_refs"][0])
    elif change == "omit":
        op["evidence_refs"].pop()
    elif change == "undeclared":
        op["evidence_refs"].append(other)
    else:
        op["claims"][0] = {key: other[key] for key in ("evidence_id", "fact_key", "value")}
    issues = audit_temporal_boundary(case, report)["leaked_items"]
    assert issues and all(item["check_code"] == "opinion_citation_boundary" for item in issues)


@pytest.mark.parametrize("change", ["duplicate", "reorder", "title", "source", "typed_value"])
def test_snapshot_preserves_each_event_with_its_original_prompt_fields(run, change):
    case, report = run
    timeline = report["case_snapshot"]["timeline"]
    if change == "duplicate":
        timeline.append(timeline[-1])
    elif change == "reorder":
        timeline.reverse()
    elif change == "typed_value":
        timeline[-1]["facts"]["imaging_complete"] = 1
    else:
        timeline[-1][change] = "changed"
    issues = audit_temporal_boundary(case, report)["leaked_items"]
    assert issues and all(item["check_code"] == "snapshot_timeline_boundary" for item in issues)


def test_legacy_omitted_default_fields_are_accepted_only_for_default_values(run):
    case, report = run
    event = report["case_snapshot"]["timeline"][0]
    del event["source_fields"]
    del event["original_timestamp"]
    del report["evidence_registry"][0]["source_field"]
    assert audit_temporal_boundary(case, report)["passed"]
    del report["evidence_registry"][0]["artifact_sha256"]
    assert not audit_temporal_boundary(case, report)["passed"]


@pytest.mark.parametrize("defect", ["lost_history", "corrupt_trigger", "future_prompt_fact"])
def test_llm_matrix_audits_the_consumed_context_against_the_original_source(monkeypatch, defect):
    case = seed_cases()[0]
    if defect == "future_prompt_fact":
        review_input = engine._review_input

        def faulty_input(frozen):
            ctx = review_input(frozen)
            # Only the provider-facing summary is damaged. The report still has valid events and refs.
            ctx["current_facts"]["post_cutoff_observation"] = "leaked"
            return ctx

        monkeypatch.setattr(engine, "_review_input", faulty_input)
        monkeypatch.setattr(llm_benchmark, "_review_input", faulty_input)
    else:
        def faulty_freeze(source, trigger_id):
            frozen = freeze_context(source, trigger_id)
            if defect == "lost_history":
                return frozen.model_copy(update={"timeline": frozen.timeline[1:]})
            edited = frozen.timeline[-1].model_copy(update={"title": "wrong source record"})
            return frozen.model_copy(update={"timeline": [*frozen.timeline[:-1], edited]})

        monkeypatch.setattr(llm_benchmark, "freeze_context", faulty_freeze)

    def factory():
        return RunLLM(_make_llm_config(), transport=_smart_llm_transport(), resolver=_public_resolver)

    matrix = llm_benchmark.evaluate_llm_ablation_matrix(case, "E002", factory)
    for method in matrix["methods"]:
        # A1 deliberately removes history, but still requires the original trigger.
        expected_pass = defect == "lost_history" and method["method_id"] == "A1"
        assert method["temporal_audit_passed"] is expected_pass
        assert method["llm_calls"] == method["agent_calls"] > 0
