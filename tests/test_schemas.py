import pytest
from pydantic import ValidationError

from mdt_demo.agents import OncologyAgent
from mdt_demo.schemas import Decision, Role, SyntheticCase, validate_opinion


def test_valid_case(case):
    assert case.case_id == "SYN-001"
    assert [event.event_id for event in case.timeline] == ["E001", "E002"]


@pytest.mark.parametrize("value", [False, 1, 0, "true", None])
def test_only_literal_synthetic_true(payload, value):
    payload["is_synthetic"] = value
    with pytest.raises(ValidationError):
        SyntheticCase.model_validate(payload)


def test_duplicate_event_ids_rejected(payload):
    payload["timeline"][1]["event_id"] = "E001"
    with pytest.raises(ValidationError, match="ID 不得重复"):
        SyntheticCase.model_validate(payload)


@pytest.mark.parametrize("value", ["2026-02-30", "01/05/2026", 1760000000, "2026-01-05T00:00:00"])
def test_invalid_dates_rejected(payload, value):
    payload["timeline"][0]["date"] = value
    with pytest.raises(ValidationError):
        SyntheticCase.model_validate(payload)


def test_timeline_is_normalized(payload):
    payload["timeline"].reverse()
    assert [event.event_id for event in SyntheticCase.model_validate(payload).timeline] == ["E001", "E002"]


def test_unknown_event_rejected_even_for_existing_model(case):
    forged = OncologyAgent().initial_review(case).model_copy(update={"supporting_event_ids": ["FAKE"]})
    with pytest.raises(ValidationError, match="不存在"):
        validate_opinion(forged, case, Role.ONCOLOGY)


def test_global_invalid_label_rejected(case):
    payload = OncologyAgent().initial_review(case).model_dump()
    payload["decision"] = "PRESCRIBE"
    with pytest.raises(ValidationError):
        validate_opinion(payload, case, Role.ONCOLOGY)


def test_label_must_belong_to_case(case):
    opinion = OncologyAgent().initial_review(case)
    restricted = SyntheticCase.model_validate({**case.model_dump(), "available_options": [Decision.DEFER_DECISION]})
    with pytest.raises(ValidationError, match="available_options"):
        validate_opinion(opinion, restricted, Role.ONCOLOGY)


def test_wrong_role_rejected(case):
    with pytest.raises(ValueError, match="角色"):
        validate_opinion(OncologyAgent().initial_review(case), case, Role.SURGERY)


def test_extra_patient_fields_rejected(payload):
    payload["patient"]["name"] = "not-allowed"
    with pytest.raises(ValidationError):
        SyntheticCase.model_validate(payload)


def test_empty_timeline_rejected(payload):
    payload["timeline"] = []
    with pytest.raises(ValidationError):
        SyntheticCase.model_validate(payload)
