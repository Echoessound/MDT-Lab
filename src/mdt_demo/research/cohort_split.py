"""Family-grouped dev/test cohort splitting and Plan §6.4 manifest builders."""

from __future__ import annotations

import hashlib
import json
import random

from pydantic import TypeAdapter, ValidationError

from .blind_review import material_from_frozen
from .engine import freeze_context
from .schemas import Identifier, ResearchCase
from .temporal_audit import AUDIT_VERSION, audit_frozen_snapshot


def _encoded(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(value) -> str:
    return hashlib.sha256(_encoded(value).encode("utf-8")).hexdigest()


def scenario_manifest_lines(rows):
    """Serialize the exact UTF-8 JSONL lines used in the manifest fingerprint."""
    for row in rows:
        yield json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"


def split_by_case_family(
    cases: list[ResearchCase],
    *,
    dev_ratio: float = 0.3,
    seed: int = 2026,
    case_family_map: dict[str, str] | None = None,
) -> dict:
    """Deterministically assign case families to dev/test with zero family leakage across splits."""
    if not 0.0 <= dev_ratio <= 1.0:
        raise ValueError("dev_ratio 必须在 0.0 与 1.0 之间。")
    case_ids = {case.case_id for case in cases}
    try:
        mapping = TypeAdapter(dict[Identifier, Identifier]).validate_python(
            {} if case_family_map is None else case_family_map, strict=True
        )
    except ValidationError:
        raise ValueError("病例族映射必须是病例 ID 到病例族 ID 的 JSON 对象，编号需符合病例 ID 格式。") from None
    unknown = mapping.keys() - case_ids
    if unknown:
        raise ValueError(f"病例族映射包含队列外病例：{', '.join(sorted(unknown))}")
    if any(mapping.get(family, family) != family for family in mapping.values()):
        raise ValueError("病例族映射必须直接指向最终族 ID，不能形成链或环。")
    case_to_family = {cid: mapping.get(cid, cid) for cid in sorted(case_ids)}
    members_by_family: dict[str, list[ResearchCase]] = {}
    for case in cases:
        members_by_family.setdefault(case_to_family[case.case_id], []).append(case)
    strata: dict[str, list[str]] = {}
    for family, members in sorted(members_by_family.items()):
        # Use the named base case when present. Otherwise prefer an unmixed
        # member, with deterministic case/version tie breaking.
        base = min(members, key=lambda c: (c.case_id != family, c.case_kind == "mixed", c.case_id, c.version))
        stratum = f"{base.case_kind}:{base.provenance[0].source_name}"
        strata.setdefault(stratum, []).append(family)

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
        "split_protocol": "family-stratified-v2",
        "split_seed": seed,
        "dev_ratio": dev_ratio,
        "total_families": len(family_to_split),
        "dev_family_count": len(dev_families),
        "test_family_count": len(test_families),
        "cross_split_family_overlap": len(overlap),
        "dev_families": sorted(dev_families),
        "test_families": sorted(test_families),
        "family_to_split": family_to_split,
        "case_to_family": case_to_family,
        "strata_summary": strata_summary,
    }


def build_dataset_and_scenario_manifests(
    cases: list[ResearchCase],
    dataset_meta: dict,
    *,
    trigger_scope: str = "all",
    dev_ratio: float = 0.3,
    seed: int = 2026,
    case_family_map: dict[str, str] | None = None,
) -> tuple[dict, list[dict]]:
    """Build Plan §6.4 dataset_manifest.json and scenario_manifest.jsonl rows."""
    if trigger_scope not in {"all", "latest"}:
        raise ValueError("trigger_scope 仅支持 all 或 latest。")
    split_info = split_by_case_family(cases, dev_ratio=dev_ratio, seed=seed, case_family_map=case_family_map)
    family_to_split = split_info["family_to_split"]

    provenance_catalog: dict[str, dict] = {}
    scenario_rows: list[dict] = []
    temporal_failures = 0
    warning_scenarios = 0

    for case in sorted(cases, key=lambda c: (c.case_id, c.version)):
        family_id = split_info["case_to_family"][case.case_id]
        for prov in case.provenance:
            declaration = prov.model_dump(mode="json")
            provenance_catalog.setdefault(_encoded(declaration), declaration)

        triggers = case.timeline if trigger_scope == "all" else case.timeline[-1:]
        for event in triggers:
            frozen = freeze_context(case, event.event_id)
            material = material_from_frozen(frozen)
            audit = audit_frozen_snapshot(case, frozen, event.event_id)
            warnings = [check["code"] for check in audit["checks"] if check["status"] == "warning"]
            if warnings:
                warning_scenarios += 1
            if not audit["passed"]:
                temporal_failures += 1
            scenario_rows.append({
                "scenario_id": f"{case.case_id}:v{case.version}:{event.event_id}",
                "case_family_id": family_id,
                "case_id": case.case_id,
                "case_version": case.version,
                "case_kind": case.case_kind,
                "split": family_to_split[family_id],
                "source_names": [p.source_name for p in case.provenance],
                "source_artifact_sha256": {p.source_name: p.artifact_sha256 for p in case.provenance},
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
                "temporal_audit_warnings": warnings,
                "temporal_audit_failures": audit["leaked_items"],
                "future_dates_in_question": audit["future_dates_in_question"],
                "same_day_events_on_cutoff": audit["same_day_events_on_cutoff"],
            })

    dev_scenarios = sum(1 for row in scenario_rows if row["split"] == "dev")
    test_scenarios = sum(1 for row in scenario_rows if row["split"] == "test")
    dataset_manifest = {
        "manifest_version": "dataset-manifest-v2",
        "trigger_scope": trigger_scope,
        "dataset": dataset_meta,
        "provenance_catalog": [provenance_catalog[k] for k in sorted(provenance_catalog)],
        "family_count": split_info["total_families"],
        "scenario_count": len(scenario_rows),
        "dev_scenario_count": dev_scenarios,
        "test_scenario_count": test_scenarios,
        "split": split_info,
        "temporal_audit_summary": {
            "audit_version": AUDIT_VERSION,
            "audited_scenarios": len(scenario_rows),
            "passed_scenarios": len(scenario_rows) - temporal_failures,
            "failed_scenarios": temporal_failures,
            "warning_scenarios": warning_scenarios,
        },
        "scenario_manifest_sha256": hashlib.sha256("".join(scenario_manifest_lines(scenario_rows)).encode("utf-8")).hexdigest(),
    }
    return dataset_manifest, scenario_rows
