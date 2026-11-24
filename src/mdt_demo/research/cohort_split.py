"""Family-grouped dev/test cohort splitting and Plan §6.4 manifest builders."""

from __future__ import annotations

import hashlib
import json
import random

from .blind_review import material_from_frozen
from .engine import freeze_context
from .schemas import ResearchCase
from .temporal_audit import audit_frozen_snapshot


def _encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value) -> str:
    return hashlib.sha256(_encoded(value).encode("utf-8")).hexdigest()


def split_by_case_family(
    cases: list[ResearchCase],
    *,
    dev_ratio: float = 0.3,
    seed: int = 2026,
) -> dict:
    """Deterministically assign case families to dev/test with zero family leakage across splits."""
    if not 0.0 <= dev_ratio <= 1.0:
        raise ValueError("dev_ratio 必须在 0.0 与 1.0 之间。")
    strata: dict[str, list[str]] = {}
    seen: set[str] = set()
    for case in sorted(cases, key=lambda c: c.case_id):
        if case.case_id in seen:
            continue
        seen.add(case.case_id)
        primary_source = case.provenance[0].source_name if case.provenance else "unknown"
        stratum = f"{case.case_kind}:{primary_source}"
        strata.setdefault(stratum, []).append(case.case_id)

    rng = random.Random(seed)
    dev_families: list[str] = []
    test_families: list[str] = []
    strata_summary: dict[str, dict] = {}

    for stratum in sorted(strata):
        members = list(strata[stratum])
        rng.shuffle(members)
        if dev_ratio == 0.0:
            n_dev = 0
        elif dev_ratio == 1.0:
            n_dev = len(members)
        elif len(members) == 1:
            # Keep single-family strata in test unless dev_ratio >= 0.5
            n_dev = 1 if dev_ratio >= 0.5 else 0
        else:
            n_dev = max(1, min(len(members) - 1, round(len(members) * dev_ratio)))
        s_dev = sorted(members[:n_dev])
        s_test = sorted(members[n_dev:])
        dev_families.extend(s_dev)
        test_families.extend(s_test)
        strata_summary[stratum] = {
            "total": len(members),
            "dev": len(s_dev),
            "test": len(s_test),
        }

    dev_set = set(dev_families)
    test_set = set(test_families)
    overlap = sorted(dev_set & test_set)
    assert not overlap, f"病例族跨集泄漏: {overlap}"

    family_to_split = {fid: "dev" for fid in dev_families}
    family_to_split.update({fid: "test" for fid in test_families})

    return {
        "split_protocol": "family-stratified-v1",
        "split_seed": seed,
        "dev_ratio": dev_ratio,
        "total_families": len(family_to_split),
        "dev_family_count": len(dev_families),
        "test_family_count": len(test_families),
        "cross_split_family_overlap": len(overlap),
        "dev_families": sorted(dev_families),
        "test_families": sorted(test_families),
        "family_to_split": family_to_split,
        "strata_summary": strata_summary,
    }


def build_dataset_and_scenario_manifests(
    cases: list[ResearchCase],
    dataset_meta: dict,
    *,
    trigger_scope: str = "all",
    dev_ratio: float = 0.3,
    seed: int = 2026,
) -> tuple[dict, list[dict]]:
    """Build Plan §6.4 dataset_manifest.json and scenario_manifest.jsonl rows."""
    if trigger_scope not in {"all", "latest"}:
        raise ValueError("trigger_scope 仅支持 all 或 latest。")
    split_info = split_by_case_family(cases, dev_ratio=dev_ratio, seed=seed)
    family_to_split = split_info["family_to_split"]

    provenance_catalog: dict[str, dict] = {}
    scenario_rows: list[dict] = []
    temporal_failures = 0

    for case in sorted(cases, key=lambda c: c.case_id):
        for prov in case.provenance:
            key = f"{prov.source_name}@{prov.dataset_version}"
            provenance_catalog.setdefault(key, prov.model_dump(mode="json"))

        triggers = case.timeline if trigger_scope == "all" else case.timeline[-1:]
        for event in triggers:
            frozen = freeze_context(case, event.event_id)
            material = material_from_frozen(frozen)
            audit = audit_frozen_snapshot(case, frozen, event.event_id)
            if not audit["passed"]:
                temporal_failures += 1
            scenario_rows.append({
                "scenario_id": f"{case.case_id}:v{case.version}:{event.event_id}",
                "case_family_id": case.case_id,
                "case_id": case.case_id,
                "case_version": case.version,
                "case_kind": case.case_kind,
                "split": family_to_split[case.case_id],
                "source_names": [p.source_name for p in case.provenance],
                "trigger_event_id": event.event_id,
                "trigger_event_type": event.event_type,
                "cutoff_date": event.occurred_at.isoformat(),
                "visible_event_count": len(frozen.timeline),
                "visible_fact_count": sum(len(ev.facts) for ev in frozen.timeline),
                "excluded_future_event_count": len(case.timeline) - len(frozen.timeline),
                "unplaced_record_count": len(case.unplaced_records),
                "frozen_input_sha256": _sha256(frozen.model_dump(mode="json")),
                "blind_material_sha256": material["input_sha256"],
                "temporal_audit_passed": audit["passed"],
                "same_day_events_on_cutoff": audit["same_day_events_on_cutoff"],
            })

    dev_scenarios = sum(1 for row in scenario_rows if row["split"] == "dev")
    test_scenarios = sum(1 for row in scenario_rows if row["split"] == "test")
    dataset_manifest = {
        "manifest_version": "dataset-manifest-v1",
        "trigger_scope": trigger_scope,
        "dataset": dataset_meta,
        "provenance_catalog": [provenance_catalog[k] for k in sorted(provenance_catalog)],
        "family_count": split_info["total_families"],
        "scenario_count": len(scenario_rows),
        "dev_scenario_count": dev_scenarios,
        "test_scenario_count": test_scenarios,
        "split": split_info,
        "temporal_audit_summary": {
            "audited_scenarios": len(scenario_rows),
            "passed_scenarios": len(scenario_rows) - temporal_failures,
            "failed_scenarios": temporal_failures,
        },
        "scenario_manifest_sha256": _sha256(scenario_rows),
    }
    return dataset_manifest, scenario_rows
