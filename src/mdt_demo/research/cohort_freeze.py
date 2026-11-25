"""Publish a cohort without executing a method, and replay its original sources."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .cohort_split import build_dataset_and_scenario_manifests, scenario_manifest_lines
from .experiments import digest, load_cases
from .schemas import ResearchCase


SourceSpec = tuple[str, Path | None, int]


def prepare_cohort(sources: list[SourceSpec], *, trigger_scope: str, dev_ratio: float,
                   seed: int, case_family_map: dict[str, str] | None = None):
    revisions = {}
    summaries = []
    for name, path, limit in sources:
        if (name == "seed") != (path is None) or not 1 <= limit <= 50:
            raise ValueError("来源需指定有效文件与 1 至 50 的病例上限；seed 使用内置病例。")
        cases, summary = load_cases(name, path, limit)
        summaries.append(summary)
        for case in cases:
            key = case.case_id, case.version
            if key in revisions and digest(revisions[key].model_dump(mode="json")) != digest(case.model_dump(mode="json")):
                raise ValueError(f"不同来源的病例 {case.case_id} v{case.version} 内容冲突，请核对编号和来源。")
            revisions[key] = case
    if not revisions:
        raise ValueError("未加载到有效病例。")
    cases = [revisions[key] for key in sorted(revisions)]
    manifest, rows = build_dataset_and_scenario_manifests(
        cases, {"sources": summaries, "total_loaded_cases": len(cases)}, trigger_scope=trigger_scope,
        dev_ratio=dev_ratio, seed=seed, case_family_map=case_family_map,
    )
    failed = [row["scenario_id"] for row in rows if not row["temporal_audit_passed"]]
    if failed:
        raise ValueError(f"有 {len(failed)} 个截点未通过冻结输入审计，例如 {failed[0]}。")
    return cases, manifest, rows


def manifest_files(manifest: dict, rows: list[dict]) -> dict[str, bytes]:
    return {
        "dataset_manifest.json": (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(),
        "scenario_manifest.jsonl": "".join(scenario_manifest_lines(rows)).encode(),
    }


def _checksums(files: dict[str, bytes]) -> bytes:
    return "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()).encode()


def inside_frozen_cohort(directory: Path) -> bool:
    root = directory.resolve()
    return any((p / "dataset_manifest.json").is_file() and (p / "SHA256SUMS").is_file()
               for p in (root, *root.parents))


def publish_cohort(directory: Path, files: dict[str, bytes]) -> None:
    """Publish both manifests and their checksums together. Reusing the same lock is idempotent."""
    if inside_frozen_cohort(directory.parent):
        raise ValueError("不能在已有冻结目录内发布另一份队列。")
    contents = {**files, "SHA256SUMS": _checksums(files)}
    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=directory.parent) as staging:
        staged = Path(staging) / "cohort"
        staged.mkdir()
        for name, data in contents.items():
            (staged / name).write_bytes(data)
        try:
            staged.rename(directory)
        except OSError:
            if not directory.is_dir():
                raise
            if ({p.name for p in directory.iterdir()} != contents.keys()
                    or any(not (directory / n).is_file() or (directory / n).read_bytes() != v
                           for n, v in contents.items())):
                raise ValueError("输出目录已有其他内容或不同的冻结清单，请指定新目录。") from None


def rebuild_frozen_cohort(directory: Path, inputs: list[Path]):
    """Verify both archived files, then reconstruct them byte-for-byte from current inputs."""
    files = {name: (directory / name).read_bytes()
             for name in ("dataset_manifest.json", "scenario_manifest.jsonl")}
    if _checksums(files) != (directory / "SHA256SUMS").read_bytes():
        raise ValueError("冻结清单的 SHA-256 校验失败。")
    locked = json.loads(files["dataset_manifest.json"])
    if locked.get("manifest_version") != "dataset-manifest-v2":
        raise ValueError("冻结清单版本不受支持。")
    source_meta = locked["dataset"]["sources"]
    if len(inputs) != sum(s["source"] != "seed" for s in source_meta):
        raise ValueError("请按冻结顺序为每个外部来源提供一个 --cohort-input。")
    paths = iter(inputs)
    sources = [(s["source"], None if s["source"] == "seed" else next(paths), s["requested_limit"])
               for s in source_meta]
    split = locked["split"]
    cases, manifest, rows = prepare_cohort(
        sources, trigger_scope=locked["trigger_scope"], dev_ratio=split["dev_ratio"],
        seed=split["split_seed"], case_family_map=split["case_to_family"],
    )
    if manifest_files(manifest, rows) != files:
        raise ValueError("当前输入、映射或截点审计与冻结清单不一致，请核对来源文件与代码版本。")
    return cases, manifest, rows


def select_split(cases: list[ResearchCase], rows: list[dict], split: str):
    if split not in {"dev", "test"}:
        raise ValueError("请选择 dev 或 test 划分。")
    selected = [row for row in rows if row["split"] == split]
    if not selected:
        raise ValueError(f"{split} 划分没有可评截点。")
    revisions = {(row["case_id"], row["case_version"]) for row in selected}
    return [case for case in cases if (case.case_id, case.version) in revisions], selected


def replay_frozen_split(directory: Path, inputs: list[Path], split: str):
    cases, manifest, rows = rebuild_frozen_cohort(directory, inputs)
    selected_cases, selected_rows = select_split(cases, rows, split)
    return selected_cases, manifest, selected_rows
