import hashlib
import json

import pytest

from mdt_demo.research.blind_review import review_material
from mdt_demo.research.cohort_split import build_dataset_and_scenario_manifests, split_by_case_family
from mdt_demo.research.datasets import prepare_import
from mdt_demo.research.engine import _review_input, freeze_context
from mdt_demo.research.schemas import ResearchCase
from mdt_demo.research.seeds import seed_cases


def test_variants_and_revisions_stay_with_their_declared_case_family():
    base, second, third = seed_cases()
    variant = base.model_copy(update={"case_id": "variant-1"})
    revision = variant.model_copy(update={"version": 2})
    cases = [variant, revision, third, second, base]
    mapping = {variant.case_id: base.case_id}
    manifest, scenarios = build_dataset_and_scenario_manifests(
        cases, {}, case_family_map=mapping, trigger_scope="latest"
    )
    assert manifest["family_count"] == 3
    assert manifest["split"]["cross_split_family_overlap"] == 0
    assert manifest["split"]["case_to_family"][variant.case_id] == base.case_id
    related = [row for row in scenarios if row["case_family_id"] == base.case_id]
    assert len(related) == 3
    assert {row["split"] for row in related} == {manifest["split"]["family_to_split"][base.case_id]}
    assert build_dataset_and_scenario_manifests(
        list(reversed(cases)), {}, case_family_map=mapping, trigger_scope="latest"
    ) == (manifest, scenarios)
    # Legacy inputs keep an independent family for each distinct case ID.
    assert split_by_case_family(cases)["total_families"] == 4


@pytest.mark.parametrize("mapping", [
    {"unknown": "F1"},
    {"LUNG-SYN-001": "LUNG-SYN-002", "LUNG-SYN-002": "F1"},
    {"LUNG-SYN-001": "LUNG-SYN-002", "LUNG-SYN-002": "LUNG-SYN-001"},
    {"LUNG-SYN-001": ""},
    {"LUNG-SYN-001": 17},
])
def test_family_map_rejects_unresolvable_entries(mapping):
    with pytest.raises(ValueError, match="病例族映射"):
        split_by_case_family(seed_cases(), case_family_map=mapping)


def test_manifest_fingerprint_matches_jsonl_and_records_source_batches_and_audit_warnings():
    a, b, _ = seed_cases()
    a = a.model_copy(update={
        "provenance": [a.provenance[0].model_copy(update={"artifact_sha256": "a" * 64})],
        "current_question": "Review scheduled for 2099-01-01.",
    })
    b = b.model_copy(update={
        "provenance": [b.provenance[0].model_copy(update={"artifact_sha256": "b" * 64})]
    })
    manifest, scenarios = build_dataset_and_scenario_manifests([a, b], {}, trigger_scope="latest")
    artifact_hashes = [entry["artifact_sha256"] for entry in manifest["provenance_catalog"]]
    assert sorted(artifact_hashes) == ["a" * 64, "b" * 64]
    assert [row["source_artifact_sha256"][a.provenance[0].source_name] for row in scenarios] == sorted(artifact_hashes)
    serialized = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in scenarios)
    assert manifest["scenario_manifest_sha256"] == hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert manifest["temporal_audit_summary"]["warning_scenarios"] == 1
    assert scenarios[0]["temporal_audit_warnings"] == ["question_future_date_scan"]
    assert scenarios[0]["future_dates_in_question"] == ["2099-01-01"]


def test_repro_pack_freezes_without_scoring_and_replays_only_registered_families(tmp_path, monkeypatch):
    from scripts import build_repro_pack as pack

    source = tmp_path / "cases.json"
    a, b, c = seed_cases()
    cases = [a, a.model_copy(update={"case_id": "variant-1"}), b, c]
    source.write_text(json.dumps({"cases": [case.model_dump(mode="json") for case in cases]}))
    lock = tmp_path / "lock"
    kwargs = dict(sources=[("research_json", source, 4)], output_dir=lock, trigger_scope="latest",
                  freeze_only=True, case_family_map={"variant-1": a.case_id})
    with monkeypatch.context() as mp:
        mp.setattr(pack, "evaluate_library", lambda *a, **kw: pytest.fail("Freeze ran an experiment"))
        pack.build_repro_pack(**kwargs)
        pack.build_repro_pack(**kwargs)
        with pytest.raises(ValueError, match="已有其他内容"):
            pack.build_repro_pack(**{**kwargs, "split_seed": 11})
    dm = json.loads((lock / "dataset_manifest.json").read_bytes())
    split = dm["split"]["family_to_split"][a.case_id]
    out = tmp_path / "replay"
    opts = dict(frozen_cohort=lock, cohort_inputs=[source], split_filter=split, output_dir=out)
    pack.build_repro_pack(**opts)
    expected = [json.loads(line) for line in (lock / "scenario_manifest.jsonl").read_bytes().splitlines()]
    scored = [json.loads(line) for line in (out / "run_index.jsonl").read_bytes().splitlines()]
    assert {r["scenario_id"] for r in scored} == {r["scenario_id"] for r in expected if r["split"] == split}
    assert {r["case_family_id"] for r in scored} == set(dm["split"][f"{split}_families"])
    with pytest.raises(ValueError, match="冻结目录以外"):
        pack.build_repro_pack(**{**opts, "output_dir": lock})
    with (lock / "scenario_manifest.jsonl").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="SHA-256"):
        pack.build_repro_pack(**{**opts, "output_dir": tmp_path / "invalid"})
    assert not (tmp_path / "invalid").exists()


def test_tcga_histology_and_record_locators_follow_the_original_file():
    raw = (
        "# field descriptions\n\n"
        "PATIENT_ID\tAGE\tSEX\tDIAGNOSIS_DATE\tPATHOLOGY_DATE\tHISTOLOGY\tNOTE\n"
        'P1\t56\tF\t2010-01-07\t2010-03-18\tRare subtype\t"two\nlines"\n'
        "# another comment\n"
        "P2\t60\tM\t2011-05-12\t\tOther subtype\t\n"
    ).encode()
    prepared = prepare_import("tcga_cbioportal_tsv", raw, 2)
    a, b = [ResearchCase.model_validate(item) for item in prepared.cases]
    assert a.provenance[0].mapping_version == prepared.summary["mapping_version"] == "tcga-clinical-mapping-v2"
    assert prepare_import("tcga_cbioportal_tsv", raw, 2).summary["batch_id"] == prepared.summary["batch_id"]
    for case, histology, physical_line in [(a, "Rare subtype", 4), (b, "Other subtype", 7)]:
        baseline = case.timeline[0]
        frozen = freeze_context(case, baseline.event_id)
        assert histology not in frozen.model_dump_json()
        assert histology not in json.dumps(_review_input(frozen))
        assert histology not in json.dumps(review_material(case, baseline.event_id))
        assert baseline.source_record_locator.endswith(f":line={physical_line}")
    assert all("histology" not in item.facts for item in a.unplaced_records)
    assert any(item.facts.get("histology") == "Other subtype" for item in b.unplaced_records)
    pathology = a.timeline[1]
    assert pathology.facts["histology"] == "Rare subtype"
    assert pathology.source_fields["histology"] == "HISTOLOGY"
    assert review_material(a, pathology.event_id)["events"][-1]["facts"]["histology"] == "Rare subtype"
    assert len(b.timeline) == 1
