from pathlib import Path

from mdt_demo.research.datasets import prepare_import
from mdt_demo.research.engine import freeze_context
from mdt_demo.research.schemas import ResearchCase


SAMPLE = Path(__file__).resolve().parents[1] / "data" / "acrin_6668" / "local_sample.json"


def test_acrin_clinical_forms_respect_evidence_availability():
    prepared = prepare_import("research_json", SAMPLE.read_bytes(), max_cases=12)
    assert prepared.summary["case_count"] == 12
    assert prepared.summary["event_count"] == 121
    assert not prepared.summary["warnings"] and not prepared.summary["rejected_count"]
    case = ResearchCase.model_validate(next(c for c in prepared.cases if c["case_id"] == "ACRIN-6668-005"))
    scan = freeze_context(case, "IM_00005_1_scan")
    interpretation = freeze_context(case, "IM_00005_2_read")
    assert all("lung_suv_peak_assessment_1" not in event.facts for event in scan.timeline)
    read = interpretation.timeline[-1]
    assert (read.occurred_at - scan.timeline[-1].occurred_at).days == 16
    assert read.facts["lung_suv_peak_assessment_1"] == 10.4
    assert read.source_fields["lung_suv_peak_assessment_1"] == "ime18"
    assert all("progression_assessment" not in event.facts for event in interpretation.timeline)
    for record in prepared.cases:
        for event in record["timeline"]:
            if event["event_type"] == "follow_up":
                assert event["facts"]["offset_days"] >= event["facts"]["assessment_offset_days"]
                assert event["source_fields"]["offset_days"] == "rec"
