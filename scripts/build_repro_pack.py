"""Build a complete Plan §6.4 reproducibility pack with family-stratified dev/test split,
temporal boundary audit, paired 8-arm scores, error attribution, LaTeX table, and reproduce.md."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from pydantic import __version__ as pydantic_version

from mdt_demo.research.cohort_split import build_dataset_and_scenario_manifests
from mdt_demo.research.evaluation import evaluate_library
from mdt_demo.research.experiments import (
    export_paper_artifacts,
    load_annotations_file,
    load_cases,
)


def _git_commit(root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL)
        return out.strip()
    except Exception:
        return "unknown"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_repro_pack(
    *,
    sources: list[tuple[str, Path | None, int]],
    output_dir: Path,
    trigger_scope: str = "all",
    dev_ratio: float = 0.3,
    split_seed: int = 2026,
    annotations_path: Path | None = None,
    split_filter: str = "all",
) -> dict:
    if split_filter not in {"all", "dev", "test"}:
        raise ValueError("split_filter 仅支持 all / dev / test。")
    all_cases = []
    source_summaries = []
    seen_ids: set[str] = set()
    for src_name, src_path, limit in sources:
        loaded, meta = load_cases(src_name, src_path, limit)
        source_summaries.append(meta)
        for case in loaded:
            if case.case_id not in seen_ids:
                seen_ids.add(case.case_id)
                all_cases.append(case)
    if not all_cases:
        raise ValueError("未加载到任何有效病例。")

    annotations = load_annotations_file(annotations_path)
    dataset_manifest, scenario_rows = build_dataset_and_scenario_manifests(
        all_cases,
        {"sources": source_summaries, "total_loaded_cases": len(all_cases)},
        trigger_scope=trigger_scope,
        dev_ratio=dev_ratio,
        seed=split_seed,
    )

    if split_filter != "all":
        allowed_families = set(dataset_manifest["split"][f"{split_filter}_families"])
        eval_cases = [c for c in all_cases if c.case_id in allowed_families]
    else:
        eval_cases = all_cases

    evaluation = evaluate_library(eval_cases, trigger_scope=trigger_scope, annotations=annotations)

    output_dir.mkdir(parents=True, exist_ok=True)
    dm_path = output_dir / "dataset_manifest.json"
    sm_path = output_dir / "scenario_manifest.jsonl"
    cfg_path = output_dir / "experiment_config.json"
    run_idx_path = output_dir / "run_index.jsonl"
    repro_path = output_dir / "reproduce.md"

    dm_path.write_text(json.dumps(dataset_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sm_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in scenario_rows),
        encoding="utf-8",
    )

    run_index_rows = []
    for s in evaluation["scenarios"]:
        run_index_rows.append({
            "scenario_id": s["scenario_id"],
            "case_family_id": s["case_family_id"],
            "split": dataset_manifest["split"]["family_to_split"].get(s["case_family_id"], "all"),
            "trigger_event_id": s["trigger_event_id"],
            "trigger_event_type": s["trigger_event_type"],
            "visible_events": s["visible_events"],
            "b3_decision": s["b3_decision"],
            "b3_calls": s["b3_calls"],
            "fixed_calls": s["fixed_calls"],
            "memory_impacted": s["memory_impacted"],
            "annotated": s["annotated"],
        })
    run_idx_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in run_index_rows),
        encoding="utf-8",
    )

    root = Path(__file__).resolve().parent.parent
    exp_config = {
        "protocol_version": evaluation["protocol_version"],
        "execution_mode": evaluation["execution_mode"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(root),
        "runtime": {"python": sys.version.split()[0], "pydantic": pydantic_version},
        "trigger_scope": trigger_scope,
        "split_filter": split_filter,
        "split_seed": split_seed,
        "dev_ratio": dev_ratio,
        "bootstrap_resamples": evaluation["paired_statistics"]["bootstrap_resamples"],
        "bootstrap_seed": evaluation["paired_statistics"]["bootstrap_seed"],
        "annotations_file": str(annotations_path) if annotations_path else None,
        "dataset_manifest_sha256": _file_sha256(dm_path),
        "scenario_manifest_sha256": _file_sha256(sm_path),
        "run_index_sha256": _file_sha256(run_idx_path),
    }
    cfg_path.write_text(json.dumps(exp_config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paper_files = export_paper_artifacts(
        output_dir,
        evaluation,
        provenance={
            "git_commit": exp_config["git_commit"],
            "dataset_manifest_sha256": exp_config["dataset_manifest_sha256"],
            "scenario_manifest_sha256": exp_config["scenario_manifest_sha256"],
            "experiment_config_sha256": _file_sha256(cfg_path),
            "run_index_sha256": exp_config["run_index_sha256"],
        },
    )

    artifacts = [
        dm_path, sm_path, cfg_path, run_idx_path,
        Path(paper_files["scores_csv"]),
        Path(paper_files["error_analysis_csv"]),
        Path(paper_files["latex_table"]),
        Path(paper_files["statistics_summary"]),
    ]
    sha_rows = "\n".join(f"| `{p.name}` | `{_file_sha256(p)}` |" for p in artifacts)
    b3 = next((m for m in evaluation["methods"] if m["method_id"] == "B3"), None)
    a3 = next((m for m in evaluation["methods"] if m["method_id"] == "A3"), None)

    repro_md = f"""# MDT Lab 实验复现包（计划书 §6.4 标准产物）

- **生成时间 (UTC)**：{exp_config['generated_at_utc']}
- **Git 提交**：`{exp_config['git_commit']}`
- **运行环境**：Python `{exp_config['runtime']['python']}` · Pydantic `{exp_config['runtime']['pydantic']}`
- **执行模式**：`{evaluation['execution_mode']}`（确定性规则仿真基准；真实大模型联调请使用 `scripts/run_llm_benchmark.py`）
- **病例族规模**：共 {dataset_manifest['family_count']} 个病例族（`dev` {dataset_manifest['split']['dev_family_count']} / `test` {dataset_manifest['split']['test_family_count']}，跨集病例族重叠 = **{dataset_manifest['split']['cross_split_family_overlap']}**）
- **评估截点**：本次评分范围 `{split_filter}`，共 {evaluation['scenario_count']} 个截点（含独立参考标注 {evaluation['annotated_scenario_count']} 个）
- **时间边界防泄漏审计**：{dataset_manifest['temporal_audit_summary']['passed_scenarios']} / {dataset_manifest['temporal_audit_summary']['audited_scenarios']} 截点通过独立重建核验（越界 = {dataset_manifest['temporal_audit_summary']['failed_scenarios']}）
- **核心对照摘录**：`B3` 均值调用 {b3['avg_calls'] if b3 else 'N/A'} 次 vs `A3` 固定全员 {a3['avg_calls'] if a3 else 'N/A'} 次（节省 **{b3['call_saving_vs_fixed_pct'] if b3 else 0}%**）；纵向记忆影响截点 {evaluation['memory_impact_scenarios']} / {evaluation['scenario_count']} 个。

## 产物清单与 SHA-256 校验指纹

| 文件名 | SHA-256 |
| --- | --- |
{sha_rows}

## 校验命令

```bash
cd "{output_dir}"
shasum -a 256 dataset_manifest.json scenario_manifest.jsonl experiment_config.json run_index.jsonl scores.csv error_analysis.csv ablation_table.tex statistics_summary.json
```

> **学术边界声明**：本复现包中的 Mock 批次用于验证工程可复算性、事件路由调用开销、纵向截断隔离与门控机制行为，不替代真实大模型运行与双盲临床专家标注的正式研究结论。
"""
    repro_path.write_text(repro_md, encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "family_count": dataset_manifest["family_count"],
        "scenario_count": evaluation["scenario_count"],
        "dev_families": dataset_manifest["split"]["dev_family_count"],
        "test_families": dataset_manifest["split"]["test_family_count"],
        "temporal_audit_failed": dataset_manifest["temporal_audit_summary"]["failed_scenarios"],
        "artifacts": [p.name for p in [*artifacts, repro_path]],
    }


def _parse_source(spec: str) -> tuple[str, Path | None, int]:
    parts = spec.split(":")
    if len(parts) == 1 and parts[0] == "seed":
        return ("seed", None, 3)
    if len(parts) == 2 and parts[0] == "seed":
        return ("seed", None, int(parts[1]))
    if len(parts) == 3:
        return (parts[0], Path(parts[1]), int(parts[2]))
    raise argparse.ArgumentTypeError(
        "来源格式应为 seed[:limit] 或 source_name:/path/to/file:limit，例如 tcia_nsclc_csv:data/raw/external/tcia_nsclc_clinical.csv:20"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="一键构建计划书 §6.4 完整科研复现包（含病例族分层划分、时序防泄漏审计与误差归因）。")
    parser.add_argument(
        "--source",
        action="append",
        type=_parse_source,
        help="可重复传入多个来源：seed[:limit] 或 source_name:path:limit。不传默认 seed:3。",
    )
    parser.add_argument("--triggers", choices=["all", "latest"], default="all")
    parser.add_argument("--dev-ratio", type=float, default=0.3)
    parser.add_argument("--split-seed", type=int, default=2026)
    parser.add_argument("--split-filter", choices=["all", "dev", "test"], default="all")
    parser.add_argument("--annotations", type=Path, help="可选：独立盲标 JSON 或仲裁 adjudication.jsonl 文件")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    sources = args.source or [("seed", None, 3)]
    summary = build_repro_pack(
        sources=sources,
        output_dir=args.output_dir,
        trigger_scope=args.triggers,
        dev_ratio=args.dev_ratio,
        split_seed=args.split_seed,
        annotations_path=args.annotations,
        split_filter=args.split_filter,
    )
    print(
        f"复现包已生成：{summary['output_dir']} · {summary['family_count']} 病例族 "
        f"(dev={summary['dev_families']}, test={summary['test_families']}) · "
        f"{summary['scenario_count']} 截点 · 时序越界={summary['temporal_audit_failed']} · "
        f"共 {len(summary['artifacts'])} 个文件。"
    )
    return 0 if summary["temporal_audit_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
