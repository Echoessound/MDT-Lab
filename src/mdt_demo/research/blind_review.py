"""Build the material actually shown to an annotator and bind references to it."""

import hashlib
import json

from ..api_schemas import APIError
from .engine import freeze_context
from .schemas import ResearchCase
from .seeds import SOURCE as SCENARIO_SOURCE, VERSION as SCENARIO_VERSION


# Imported clinical facts use an open vocabulary. Keep custom clinical fields,
# but never return experiment outputs stored alongside those fields.
SYSTEM_FIELDS = {
    "expected_decision", "gold_label", "final_decision", "pre_gate_decision",
    "mock_expected", "mock_decision", "model_decision", "selected_agents", "skipped_agents",
    "required_agents", "routing", "routing_mode", "safety", "rule_id",
}


def material_from_frozen(frozen: ResearchCase) -> dict:
    trigger_id = frozen.timeline[-1].event_id
    scenario_id = f"{frozen.case_id}:v{frozen.version}:{trigger_id}"
    events = []
    has_seed_source = any(source.source_name == SCENARIO_SOURCE and source.dataset_version == SCENARIO_VERSION
                          for source in frozen.provenance)
    for event in frozen.timeline:
        is_seed_event = has_seed_source and event.source == SCENARIO_SOURCE and event.introduced_in_version == 1
        excluded = SYSTEM_FIELDS
        if is_seed_event:
            # Seed narratives describe the scenario author's intended conflict.
            excluded = excluded | {"record_note", "review_note"}
        events.append({
            "event_id": event.event_id,
            "occurred_at": event.occurred_at.isoformat(),
            "event_type": event.event_type,
            "title": "合成病程记录" if is_seed_event else event.title,
            "facts": {key: value for key, value in event.facts.items() if key not in excluded},
        })
    material = {"scenario_id": scenario_id, "events": events}
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**material, "input_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def review_material(case: ResearchCase, trigger_event_id: str) -> dict:
    if not any(event.event_id == trigger_event_id for event in case.timeline):
        raise APIError(404, "EVENT_NOT_FOUND", "该触发事件不属于所选病例版本。")
    return material_from_frozen(freeze_context(case, trigger_event_id))


def validate_reference(material: dict, annotation: dict) -> None:
    """Legacy references can omit a fingerprint. A supplied binding must match."""
    fingerprint = annotation.get("input_sha256")
    if fingerprint is not None and fingerprint != material["input_sha256"]:
        raise APIError(409, "ANNOTATION_INPUT_MISMATCH",
                       f"场景 {material['scenario_id']} 的盲标材料指纹已变化，请用对应版本重新核对。")
    evidence_ids = annotation.get("evidence_ids", [])
    if evidence_ids:
        visible = {f"{event['event_id']}:{key}" for event in material["events"] for key in event["facts"]}
        if not visible.issuperset(evidence_ids):
            raise APIError(422, "ANNOTATION_EVIDENCE_OUT_OF_SCOPE",
                           f"场景 {material['scenario_id']} 的关键证据须全部来自本截点可见事实。")
