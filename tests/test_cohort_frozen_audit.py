import pytest

from mdt_demo.research.engine import freeze_context
from mdt_demo.research.schemas import ResearchCase
from mdt_demo.research.seeds import seed_cases
from mdt_demo.research.temporal_audit import audit_frozen_snapshot


@pytest.mark.parametrize("changed", ["provenance", "patient", "data_notes"])
def test_frozen_manifest_audit_catches_static_fields_rewritten_after_cutoff(changed):
    case = seed_cases()[0]
    frozen = freeze_context(case, "E002")
    payload = frozen.model_dump(mode="json")
    if changed == "provenance":
        payload["provenance"][0]["artifact_sha256"] = "a" * 64
    elif changed == "patient":
        payload["patient"]["age"] += 1
    else:
        payload["data_notes"].append("后续事件摘要")
    result = audit_frozen_snapshot(case, ResearchCase.model_validate(payload), "E002")
    assert not result["passed"]
    assert result["leaked_count"] == 1
    issue, = result["leaked_items"]
    assert issue["check_code"] == "snapshot_metadata_integrity"
    assert issue["location"] == f"case_snapshot.{changed}"


def test_chinese_prose_future_iso_date_is_a_warning_even_without_spaces():
    payload = seed_cases()[0].model_dump(mode="json")
    payload["current_question"] = "截至2099-01-01的报告于2099-01-01收到。编号12099-02-011，日期2099-02-30无效。"
    case = ResearchCase.model_validate(payload)
    result = audit_frozen_snapshot(case, freeze_context(case, "E002"), "E002")
    assert result["passed"]
    assert result["future_dates_in_question"] == ["2099-01-01"]
    assert any(check["code"] == "question_future_date_scan" and check["status"] == "warning"
               for check in result["checks"])
