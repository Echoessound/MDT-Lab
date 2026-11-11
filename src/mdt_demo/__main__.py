"""python -m mdt_demo --case data/synthetic_case_001.json --mode mock"""

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from pydantic import ValidationError

from . import __version__
from .config import Settings
from .llm import LLMNotImplementedError
from .orchestrator import MDTOrchestrator


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MDT 合成病例科研流程演示（离线 Mock）")
    parser.add_argument("--case", type=Path, required=True, help="完全虚构的病例 JSON")
    parser.add_argument("--mode", choices=("mock", "llm"), default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(mode=args.mode, output_dir=args.output_dir)
        orchestrator = MDTOrchestrator(mode=settings.mode, output_dir=settings.output_dir)
        payload = json.loads(args.case.read_text(encoding="utf-8"))
        report = orchestrator.run(payload)
    except LLMNotImplementedError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print("病例校验失败：", file=sys.stderr)
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            location = ".".join(map(str, error["loc"])) or "case"
            print(f"  {location}: {error['msg']}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, UnicodeError):
        print("输入错误：病例文件必须是合法的 UTF-8 JSON。", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"文件读写失败（{type(exc).__name__}），请检查病例路径及输出目录权限。", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    print(f"MDT Demo v{__version__}\nMode: {report.mode}\nCase: {report.case_id}")
    print(f"run_id: {report.run_id}")
    for opinion in report.initial_opinions:
        print(f"  initial/{opinion.agent_name}: {opinion.decision}")
    print(f"Discussion rounds: {report.discussion_rounds}")
    print(f"Final decision: {report.final_decision}\nStatus: {report.status}")
    output = (settings.output_dir / report.run_id).resolve()
    print(f"Output: {output}\nReport: {output / 'report.json'}\nAudit: {output / 'audit.jsonl'}")
    for warning in report.warnings:
        print(f"Warning: {warning}")
    print(report.disclaimer)
    return 0 if report.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
