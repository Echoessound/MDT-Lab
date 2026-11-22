"""Run the paired Mock experiment protocol from local cases or source files."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

from mdt_demo.api_schemas import APIError
from mdt_demo.research.experiments import bind_plan, export_results, load_cases, plan_batch, run_scenario


def main():
    parser = argparse.ArgumentParser(description="按病例与触发截点批量运行本地 Mock 对照，导出可复算的 JSON。")
    parser.add_argument("--source", choices=["seed", "tcia_nsclc_csv", "synthea_csv"], default="seed")
    parser.add_argument("--input", type=Path, help="来源文件。seed 使用仓内病例。")
    parser.add_argument("--max-cases", type=int, default=3, help="按来源顺序最多纳入的病例数，默认 3")
    parser.add_argument("--triggers", choices=["all", "latest"], default="all")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.max_cases <= 50:
        parser.error("--max-cases 范围为 1 至 50")
    if (args.source == "seed") != (args.input is None):
        parser.error("外部来源必须提供 --input，内置 seed 来源无需文件")
    try:
        cases, dataset = load_cases(args.source, args.input, args.max_cases)
        if not cases:
            raise ValueError("当前预检未纳入病例，请检查源文件及导入器的排除原因。")
        plan = plan_batch(cases, dataset, args.triggers)
        case_index = {case.case_id: case for case in cases}
        args.output_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = args.output_dir / "checkpoint.sqlite3"
        if (args.output_dir / "results.json").exists() and not checkpoint.exists():
            raise ValueError("输出目录已有结果文件，但缺少对应检查点。请为新批次指定新的目录。")
        with closing(sqlite3.connect(checkpoint, timeout=120)) as db:
            bind_plan(db, plan)
            for scenario in plan["scenarios"]:
                run_scenario(db, case_index[scenario["case_id"]], scenario)
            summary = export_results(db, plan, args.output_dir)
    except APIError as error:
        parser.exit(2, f"{error.code}: {error.message}\n")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"{error}\n")
    print(f"{args.output_dir / 'results.json'} · {summary['families']} 个病例族，"
          f"{summary['completed']}/{summary['scenarios']} 个截点完成，{summary['method_rows']} 条方法记录。")
    return int(summary["failed"] > 0)


if __name__ == "__main__":
    sys.exit(main())
