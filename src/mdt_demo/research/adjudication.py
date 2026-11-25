"""Multi-rater independent blind review, inter-rater agreement (Cohen's kappa / Jaccard),
and consensus adjudication store (Plan §4 G03, §5 S3, §6.1, §6.4)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from itertools import chain, combinations
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ..api_schemas import APIError
from ..schemas import Decision
from .schemas import ROLES, Role

DECISIONS: tuple[Decision, ...] = (
    "READY_FOR_REVIEW",
    "NEED_MORE_INFORMATION",
    "DEFER_DECISION",
)
DEFAULT_PROTOCOL_VERSION = "annotation-protocol-v1"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MultiRaterSubmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: str = Field(min_length=1, max_length=80)
    case_version: int = Field(ge=1, strict=True)
    trigger_event_id: str = Field(min_length=1, max_length=80)
    annotator_id: str = Field(min_length=1, max_length=80)
    protocol_version: str = Field(default=DEFAULT_PROTOCOL_VERSION, min_length=1, max_length=80)
    required_agents: list[Role] = Field(min_length=1, max_length=4)
    expected_decision: Decision
    input_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_ids: list[Annotated[str, Field(min_length=3, max_length=161)]] = Field(default_factory=list, max_length=80)
    missing_fields: list[str] = Field(default_factory=list, max_length=30)
    expected_conflicts: list[str] = Field(default_factory=list, max_length=30)
    rationale: str = Field(default="", max_length=2000)


class AdjudicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    case_id: str = Field(min_length=1, max_length=80)
    case_version: int = Field(ge=1, strict=True)
    trigger_event_id: str = Field(min_length=1, max_length=80)
    adjudicator_id: str = Field(min_length=1, max_length=80)
    protocol_version: str = Field(default=DEFAULT_PROTOCOL_VERSION, min_length=1, max_length=80)
    required_agents: list[Role] = Field(min_length=1, max_length=4)
    expected_decision: Decision
    input_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    evidence_ids: list[Annotated[str, Field(min_length=3, max_length=161)]] = Field(default_factory=list, max_length=80)
    missing_fields: list[str] = Field(default_factory=list, max_length=30)
    expected_conflicts: list[str] = Field(default_factory=list, max_length=30)
    adjudication_rationale: str = Field(default="", max_length=2000)


def _dedup_clean(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _agreement_from_matrix(matrix: dict, *, fixed_raters: bool) -> dict:
    n = sum(sum(row.values()) for row in matrix.values())
    matched = sum(matrix[label][label] for label in matrix)
    # Cohen's chance model uses the two annotators' separate marginals.
    expected = sum(
        sum(matrix[label].values()) * sum(row[label] for row in matrix.values())
        for label in matrix
    )
    return {
        "pair_count": n,
        "raw_agreement": round(matched / n, 4) if n else None,
        "expected_agreement": round(expected / (n * n), 4) if fixed_raters and n else None,
        "cohens_kappa": (
            round((matched * n - expected) / (n * n - expected), 4)
            if fixed_raters and n * n != expected else None
        ),
    }


def _paired_agreement(comparisons: Iterable[tuple[dict, dict]], *, fixed_raters: bool) -> dict:
    decisions = {a: {b: 0 for b in DECISIONS} for a in DECISIONS}
    roles = {role: {a: {b: 0 for b in (False, True)} for a in (False, True)} for role in ROLES}
    for left, right in comparisons:
        decisions[left["expected_decision"]][right["expected_decision"]] += 1
        for role, matrix in roles.items():
            matrix[role in left["required_agents"]][role in right["required_agents"]] += 1
    return {
        "decision_agreement": {**_agreement_from_matrix(decisions, fixed_raters=fixed_raters),
                               "confusion_matrix": decisions},
        "per_role": {role: _agreement_from_matrix(matrix, fixed_raters=fixed_raters)
                     for role, matrix in roles.items()},
    }


def detect_disagreement_types(submissions: list[dict]) -> list[str]:
    """Identify disagreement dimensions across ≥ 2 independent submissions."""
    if len(submissions) < 2:
        return []
    kinds: list[str] = []
    if len({item["expected_decision"] for item in submissions}) > 1:
        kinds.append("decision")
    if len({frozenset(item["required_agents"]) for item in submissions}) > 1:
        kinds.append("required_agents")
    if len({frozenset(item.get("missing_fields", [])) for item in submissions}) > 1:
        kinds.append("missing_fields")
    return kinds


def compute_agreement_report(
    submissions_by_scenario: dict[str, dict[str, dict]],
    adjudications: dict[str, dict],
) -> dict:
    """Compute inter-rater agreement (Cohen's kappa, Jaccard overlap) and disagreement queue."""
    by_pair: dict[tuple[str, str], list[tuple[dict, dict]]] = defaultdict(list)
    specialist_jaccards: list[float] = []
    specialist_exact_hits = 0
    evidence_jaccards: list[float] = []
    missing_jaccards: list[float] = []
    annotator_counts: dict[str, int] = {}
    disputed: list[dict] = []
    multi_rated_count = 0

    for scenario_id in sorted(submissions_by_scenario):
        by_rater = submissions_by_scenario[scenario_id]
        if not by_rater:
            continue
        items = [by_rater[rater] for rater in sorted(by_rater)]
        for item in items:
            aid = item["annotator_id"]
            annotator_counts[aid] = annotator_counts.get(aid, 0) + 1
        if len(items) < 2:
            continue
        multi_rated_count += 1
        kinds = detect_disagreement_types(items)
        if kinds:
            disputed.append({
                "scenario_id": scenario_id,
                "case_id": items[0]["case_id"],
                "case_version": items[0]["case_version"],
                "trigger_event_id": items[0]["trigger_event_id"],
                "annotators": [item["annotator_id"] for item in items],
                "disagreement_types": kinds,
                "adjudicated": scenario_id in adjudications,
                "submissions": items,
                "adjudication": adjudications.get(scenario_id),
            })

        for left, right in combinations(items, 2):
            by_pair[(left["annotator_id"], right["annotator_id"])].append((left, right))
            l_roles, r_roles = set(left["required_agents"]), set(right["required_agents"])
            specialist_jaccards.append(_jaccard(l_roles, r_roles))
            specialist_exact_hits += int(l_roles == r_roles)

            l_ev, r_ev = set(left.get("evidence_ids", [])), set(right.get("evidence_ids", []))
            if l_ev or r_ev:
                evidence_jaccards.append(_jaccard(l_ev, r_ev))

            l_miss, r_miss = set(left.get("missing_fields", [])), set(right.get("missing_fields", []))
            if l_miss or r_miss:
                missing_jaccards.append(_jaccard(l_miss, r_miss))

    pair_reports = [
        {"annotators": list(raters), **_paired_agreement(by_pair[raters], fixed_raters=True)}
        for raters in sorted(by_pair)
    ]
    pooled = (pair_reports[0] if len(pair_reports) == 1
              else _paired_agreement(chain.from_iterable(by_pair.values()), fixed_raters=False))
    decision_stats = pooled["decision_agreement"]
    total_pairs = decision_stats["pair_count"]
    unadjudicated = sum(1 for item in disputed if not item["adjudicated"])
    note = (
        f"共 {len(submissions_by_scenario)} 个截点含独立初标，其中 {multi_rated_count} 个截点有 ≥2 位标注人完成盲标，"
        f"检出 {len(disputed)} 个争议截点（已仲裁 {len(disputed) - unadjudicated} 个，待仲裁 {unadjudicated} 个）。"
    )
    if len(pair_reports) > 1:
        note += f"共有 {len(pair_reports)} 种标注人配对，整体原始一致率按配对次数计算，Cohen's κ 按固定标注人组合分别报告。"
    elif multi_rated_count > 0 and decision_stats["cohens_kappa"] is None:
        note += "三分类标签全部落入同一类别（p_e = 1.0），Cohen's κ 不可定义，请参考原始一致率。"
    elif multi_rated_count == 0:
        note += "需要至少 2 位独立标注人对同一截点完成盲标后，方可计算 Cohen's κ 与专科集合重合度。"

    return {
        "protocol_version": DEFAULT_PROTOCOL_VERSION,
        "scenarios_with_submissions": len(submissions_by_scenario),
        "multi_rated_scenarios": multi_rated_count,
        "disputed_count": len(disputed),
        "adjudicated_count": len(adjudications),
        "unadjudicated_disputes": unadjudicated,
        "annotator_counts": dict(sorted(annotator_counts.items())),
        "decision_agreement": decision_stats,
        "rater_pair_agreement": pair_reports,
        "specialist_agreement": {
            "pair_count": total_pairs,
            "mean_jaccard": round(sum(specialist_jaccards) / total_pairs, 4) if total_pairs else None,
            "exact_set_agreement": round(specialist_exact_hits / total_pairs, 4) if total_pairs else None,
            "per_role": pooled["per_role"],
        },
        "evidence_mean_jaccard": (
            round(sum(evidence_jaccards) / len(evidence_jaccards), 4) if evidence_jaccards else None
        ),
        "missing_fields_mean_jaccard": (
            round(sum(missing_jaccards) / len(missing_jaccards), 4) if missing_jaccards else None
        ),
        "disputed_scenarios": disputed,
        "summary_note": note,
    }


class MultiRaterStore:
    """Thread-safe local persistence for multi-rater blind reviews and consensus adjudications."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._state: dict = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"submissions": {}, "adjudications": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "submissions": data.get("submissions", {}) if isinstance(data.get("submissions"), dict) else {},
                    "adjudications": data.get("adjudications", {}) if isinstance(data.get("adjudications"), dict) else {},
                }
        except (OSError, ValueError):
            pass
        return {"submissions": {}, "adjudications": {}}

    def _save(self, state: dict) -> None:
        tmp = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as fp:
                tmp = Path(fp.name)
                json.dump(state, fp, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
            self._state = state
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def own_submission(self, scenario_id: str, annotator_id: str) -> dict | None:
        """Strictly return only the caller's own blind submission for this scenario."""
        with self._lock:
            return self._state["submissions"].get(scenario_id, {}).get(annotator_id)

    def submission_counts(self) -> dict[str, int]:
        with self._lock:
            return {sid: len(raters) for sid, raters in self._state["submissions"].items()}

    def scenario_rater_status(self, scenario_id: str, annotator_id: str | None = None) -> dict:
        with self._lock:
            raters = self._state["submissions"].get(scenario_id, {})
            return {
                "submission_count": len(raters),
                "own_submitted": bool(annotator_id and annotator_id in raters),
                "adjudicated": scenario_id in self._state["adjudications"],
            }

    def upsert_submission(self, scenario_id: str, payload: MultiRaterSubmissionInput) -> dict:
        expected_id = f"{payload.case_id}:v{payload.case_version}:{payload.trigger_event_id}"
        if scenario_id != expected_id:
            raise APIError(422, "SCENARIO_ID_MISMATCH", f"场景编号应为 {expected_id}。")
        now = _utcnow()
        with self._lock:
            existing = self._state["submissions"].get(scenario_id, {}).get(payload.annotator_id)
            record = {
                **payload.model_dump(mode="json"),
                "scenario_id": scenario_id,
                "required_agents": list(dict.fromkeys(payload.required_agents)),
                "evidence_ids": _dedup_clean(payload.evidence_ids),
                "missing_fields": _dedup_clean(payload.missing_fields),
                "expected_conflicts": _dedup_clean(payload.expected_conflicts),
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
            submissions = {k: dict(v) for k, v in self._state["submissions"].items()}
            submissions.setdefault(scenario_id, {})[payload.annotator_id] = record
            self._save({"submissions": submissions, "adjudications": dict(self._state["adjudications"])})
            return record

    def delete_submission(self, scenario_id: str, annotator_id: str) -> dict:
        with self._lock:
            by_rater = self._state["submissions"].get(scenario_id, {})
            if annotator_id not in by_rater:
                raise APIError(404, "SUBMISSION_NOT_FOUND", "未找到该标注人在此截点的初标记录。")
            submissions = {k: dict(v) for k, v in self._state["submissions"].items()}
            del submissions[scenario_id][annotator_id]
            if not submissions[scenario_id]:
                del submissions[scenario_id]
            self._save({"submissions": submissions, "adjudications": dict(self._state["adjudications"])})
            return {"deleted": True, "scenario_id": scenario_id, "annotator_id": annotator_id}

    def list_submissions(self) -> list[dict]:
        with self._lock:
            rows = []
            for sid in sorted(self._state["submissions"]):
                for rater in sorted(self._state["submissions"][sid]):
                    rows.append(self._state["submissions"][sid][rater])
            return rows

    def submissions_for_scenario(self, scenario_id: str) -> list[dict]:
        with self._lock:
            by_rater = self._state["submissions"].get(scenario_id, {})
            return [by_rater[r] for r in sorted(by_rater)]

    def upsert_adjudication(self, scenario_id: str, payload: AdjudicationInput) -> dict:
        expected_id = f"{payload.case_id}:v{payload.case_version}:{payload.trigger_event_id}"
        if scenario_id != expected_id:
            raise APIError(422, "SCENARIO_ID_MISMATCH", f"场景编号应为 {expected_id}。")
        now = _utcnow()
        with self._lock:
            initial_items = self.submissions_for_scenario(scenario_id)
            disagreements = detect_disagreement_types(initial_items)
            existing = self._state["adjudications"].get(scenario_id)
            record = {
                **payload.model_dump(mode="json"),
                "scenario_id": scenario_id,
                "required_agents": list(dict.fromkeys(payload.required_agents)),
                "evidence_ids": _dedup_clean(payload.evidence_ids),
                "missing_fields": _dedup_clean(payload.missing_fields),
                "expected_conflicts": _dedup_clean(payload.expected_conflicts),
                "resolved_from_annotators": [item["annotator_id"] for item in initial_items],
                "source_disagreement_types": disagreements,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
            adjudications = {**self._state["adjudications"], scenario_id: record}
            self._save({"submissions": {k: dict(v) for k, v in self._state["submissions"].items()},
                        "adjudications": adjudications})
            return record

    def delete_adjudication(self, scenario_id: str) -> dict:
        with self._lock:
            if scenario_id not in self._state["adjudications"]:
                raise APIError(404, "ADJUDICATION_NOT_FOUND", "未找到该截点的仲裁记录。")
            adjudications = dict(self._state["adjudications"])
            del adjudications[scenario_id]
            self._save({"submissions": {k: dict(v) for k, v in self._state["submissions"].items()},
                        "adjudications": adjudications})
            return {"deleted": True, "scenario_id": scenario_id}

    def list_adjudications(self) -> list[dict]:
        with self._lock:
            return [self._state["adjudications"][sid] for sid in sorted(self._state["adjudications"])]

    def map_adjudications(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._state["adjudications"])

    def agreement_report(self) -> dict:
        with self._lock:
            return compute_agreement_report(self._state["submissions"], self._state["adjudications"])

    def resolve_gold_references(self, fallback_single: dict[str, dict] | None = None) -> dict[str, dict]:
        """Resolve scoring gold references: adjudicated consensus > unanimous multi-rater > legacy single."""
        resolved: dict[str, dict] = {}
        if fallback_single:
            for sid, item in fallback_single.items():
                resolved[sid] = {**item, "reference_source": "single_annotator"}
        with self._lock:
            for sid, by_rater in self._state["submissions"].items():
                items = [by_rater[r] for r in sorted(by_rater)]
                if len(items) >= 2 and not detect_disagreement_types(items):
                    first = items[0]
                    # Union evidence IDs agreed across raters, keeping the shared decision & roles.
                    resolved[sid] = {
                        "scenario_id": sid,
                        "case_id": first["case_id"],
                        "case_version": first["case_version"],
                        "trigger_event_id": first["trigger_event_id"],
                        "annotator_id": ",".join(item["annotator_id"] for item in items),
                        "required_agents": first["required_agents"],
                        "expected_decision": first["expected_decision"],
                        "input_sha256": first.get("input_sha256"),
                        "evidence_ids": _dedup_clean([eid for it in items for eid in it.get("evidence_ids", [])]),
                        "missing_fields": first.get("missing_fields", []),
                        "rationale": first.get("rationale", ""),
                        "reference_source": "unanimous_multi_rater",
                    }
            for sid, adj in self._state["adjudications"].items():
                resolved[sid] = {
                    "scenario_id": sid,
                    "case_id": adj["case_id"],
                    "case_version": adj["case_version"],
                    "trigger_event_id": adj["trigger_event_id"],
                    "annotator_id": adj["adjudicator_id"],
                    "required_agents": adj["required_agents"],
                    "expected_decision": adj["expected_decision"],
                    "input_sha256": adj.get("input_sha256"),
                    "evidence_ids": adj.get("evidence_ids", []),
                    "missing_fields": adj.get("missing_fields", []),
                    "rationale": adj.get("adjudication_rationale", ""),
                    "reference_source": "adjudicated_consensus",
                }
        return resolved

    def export_annotations_jsonl(self) -> str:
        """Export independent initial submissions as standard Plan §6.4 annotations.jsonl."""
        rows = self.list_submissions()
        return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)

    def export_adjudication_jsonl(self) -> str:
        """Export consensus adjudications as standard Plan §6.4 adjudication.jsonl."""
        rows = self.list_adjudications()
        return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
