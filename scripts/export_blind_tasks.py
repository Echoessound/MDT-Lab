"""Export the cutoff materials for one split of a verified frozen cohort."""

import argparse
import filecmp
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from mdt_demo.api_schemas import APIError
from mdt_demo.research.blind_review import review_material
from mdt_demo.research.cohort_freeze import inside_frozen_cohort, replay_frozen_split


def export_blind_tasks(directory: Path, inputs: list[Path], split: str, output: Path) -> int:
    frozen_root = directory.resolve()
    if inside_frozen_cohort(output.parent) or output.resolve().is_relative_to(frozen_root):
        raise ValueError("盲标任务文件须保存在冻结队列目录之外。")
    cases, _, rows = replay_frozen_split(directory, inputs, split)
    by_version = {(case.case_id, case.version): case for case in cases}
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        staged = Path(staging) / "tasks.jsonl"
        with staged.open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                case = by_version[row["case_id"], row["case_version"]]
                material = review_material(case, row["trigger_event_id"])
                if (material["scenario_id"] != row["scenario_id"] or
                        material["input_sha256"] != row["blind_material_sha256"]):
                    raise ValueError(f"盲审材料与冻结截点 {row['scenario_id']} 的编号或指纹不符。")
                task = {key: material[key] for key in ("scenario_id", "events", "input_sha256")}
                stream.write(json.dumps(task, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
        # A second exporter may publish at the same path while the materials are rebuilt.
        try:
            os.link(staged, output)
        except FileExistsError:
            if not output.is_file() or not filecmp.cmp(staged, output, shallow=False):
                raise ValueError("目标路径已有不同内容，请为本次盲标任务选择新文件。") from None
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="导出冻结队列单一划分的逐截点盲审材料。")
    parser.add_argument("--frozen-cohort", type=Path, required=True, help="含两份清单及 SHA256SUMS 的冻结目录")
    parser.add_argument("--cohort-input", type=Path, action="append", default=[],
                        help="按冻结清单顺序为每个非 seed 来源传入一个文件，可重复")
    parser.add_argument("--split-filter", choices=["dev", "test"], required=True, help="本次分配的划分")
    parser.add_argument("--output", type=Path, required=True, help="冻结目录以外的 JSONL 任务文件")
    args = parser.parse_args()
    try:
        count = export_blind_tasks(args.frozen_cohort, args.cohort_input, args.split_filter, args.output)
    except APIError as exc:
        parser.exit(1, f"{exc.code}: {exc.message}\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"导出失败：{exc}\n")
    print(f"{args.split_filter} 划分已核对并导出 {count} 个盲标截点至 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
