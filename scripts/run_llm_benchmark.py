"""Run G01 real-LLM smoke validation or paired LLM ablation experiments (Plan G01 / G04).

Reads API key from environment variable (default: MDT_LLM_API_KEY) so secrets never
appear in shell history, manifest JSON, or reproduction artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from pydantic import SecretStr, ValidationError
from dotenv import dotenv_values

from mdt_demo.api_schemas import APIError
from mdt_demo.research.cohort_freeze import inside_frozen_cohort, replay_frozen_split
from mdt_demo.research.cohort_split import scenario_manifest_lines
from mdt_demo.research.experiments import load_cases
from mdt_demo.research.llm_benchmark import (
    aggregate_usage_meters,
    evaluate_llm_ablation_matrix,
    g01_request_plan,
    run_g01_smoke_suite,
)
from mdt_demo.research.provider import RunLLM, default_response_format, is_deepseek_endpoint, prompt_version
from mdt_demo.research.provider_config import LLMConfigInput, ProviderError


def _format_known_usage(suite: dict) -> str:
    return (
        f"已知Token(输入/输出)={suite['known_prompt_tokens']}({suite['prompt_usage_requests']}/{suite['llm_calls']})/"
        f"{suite['known_completion_tokens']}({suite['completion_usage_requests']}/{suite['llm_calls']})"
    )


def _paired_inputs(args):
    if args.frozen_cohort is not None:
        cases, manifest, rows = replay_frozen_split(args.frozen_cohort, args.cohort_input, args.split_filter)
        manifest_bytes = (args.frozen_cohort / "dataset_manifest.json").read_bytes()
        if json.loads(manifest_bytes) != manifest:
            raise ValueError("复核期间队列清单发生变化，请使用同一份冻结目录。")
        selected_bytes = "".join(scenario_manifest_lines(rows)).encode("utf-8")
        dataset = {
            "source": "frozen_cohort",
            "split_filter": args.split_filter,
            "dataset_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "scenario_manifest_sha256": manifest["scenario_manifest_sha256"],
            "selected_scenario_manifest_sha256": hashlib.sha256(selected_bytes).hexdigest(),
            "cohort_family_count": manifest["family_count"],
            "cohort_scenario_count": manifest["scenario_count"],
            "selected_family_count": len({row["case_family_id"] for row in rows}),
            "selected_scenario_count": len(rows),
        }
    else:
        source = args.source or "seed"
        if (source == "seed") != (args.input is None):
            raise ValueError("外部来源必须提供 --input，seed 来源无需文件")
        cases, dataset = load_cases(source, args.input, 3 if args.max_cases is None else args.max_cases)
        rows = [
            {"scenario_id": f"{case.case_id}:v{case.version}:{event.event_id}",
             "case_id": case.case_id, "case_version": case.version, "trigger_event_id": event.event_id}
            for case in cases
            for event in (case.timeline if args.triggers == "all" else case.timeline[-1:])
        ]
    if not rows:
        raise ValueError("所选队列没有可执行的截点。")
    cases_by_version = {(case.case_id, case.version): case for case in cases}
    return dataset, [(row, cases_by_version[row["case_id"], row["case_version"]]) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="执行计划书 G01 真实模型兼容性联调或配对 LLM 消融基准（不泄露密钥）。"
    )
    parser.add_argument("--base-url", help="OpenAI 兼容服务端点，如 https://api.openai.com/v1")
    parser.add_argument("--model", help="目标模型标识")
    parser.add_argument("--provider", default="openai-compatible", help="提供方标签（仅用于记录）")
    parser.add_argument("--api-key-env", default="MDT_LLM_API_KEY", help="存放密钥的环境变量名")
    parser.add_argument("--env-file", type=Path, help="可选的本机 .env 文件；进程环境变量优先")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json-mode", choices=["json_schema", "json_object"],
                        help="输出约束。默认使用 json_schema；DeepSeek 官方端点默认使用 json_object。")
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="相邻场景/方法组间限流间隔秒数")
    parser.add_argument("--mode", choices=["preflight", "smoke", "paired"], default="smoke",
                        help="preflight 仅在本地检查 G01 参数和请求上限，smoke 执行三场景联调，paired 执行配对消融")
    parser.add_argument("--source", choices=["seed", "tcia_nsclc_csv", "synthea_csv", "tcga_cbioportal_tsv", "research_json"])
    parser.add_argument("--input", type=Path, help="外部来源文件（paired 模式非 seed 来源必填）")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--triggers", choices=["all", "latest"])
    parser.add_argument("--frozen-cohort", type=Path, help="paired 模式使用冻结清单的目录")
    parser.add_argument("--cohort-input", type=Path, action="append", default=[],
                        help="按冻结清单的来源顺序传入各非 seed 来源的本地文件，可重复")
    parser.add_argument("--split-filter", choices=["dev", "test"], help="运行冻结队列时必须指定开发集或测试集")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.frozen_cohort is not None:
        if args.mode != "paired" or args.split_filter is None:
            parser.error("--frozen-cohort 需要 --mode paired 和显式的 --split-filter dev 或 test")
        if any(arg is not None for arg in (args.source, args.input, args.max_cases, args.triggers)):
            parser.error("--frozen-cohort 已固定来源和截点，与 --source/--input/--max-cases/--triggers 互斥")
    elif args.split_filter is not None or args.cohort_input:
        parser.error("--split-filter 和 --cohort-input 需要配合 --frozen-cohort 使用")

    api_key = os.environ.get(args.api_key_env)
    if args.env_file is not None and api_key is None:
        if not args.env_file.is_file():
            parser.error("指定的 --env-file 文件不存在。")
        api_key = dotenv_values(args.env_file).get(args.api_key_env)
    api_key = (api_key or "").strip()
    config = None
    issues = []
    if not api_key:
        issues.append({"field": "api_key", "reason": "missing", "environment_variable": args.api_key_env})
    try:
        config = LLMConfigInput(
            provider=args.provider,
            base_url=args.base_url,
            model=args.model,
            api_key=SecretStr(api_key) if api_key else None,
            timeout_seconds=args.timeout,
            temperature=args.temperature,
            max_output_tokens=args.max_tokens,
        )
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_url=False, include_context=False):
            field = error["loc"][0]
            absent = field in {"base_url", "model"} and not getattr(args, field)
            issues.append({"field": field, "reason": "missing" if absent else error["type"]})

    if args.json_mode is None:
        args.json_mode = default_response_format(config) if config else "json_schema"
    thinking_mode = "disabled" if config and is_deepseek_endpoint(config) else "provider_default"
    if inside_frozen_cohort(args.output_dir):
        parser.error("请将运行结果保存到冻结目录以外。")
    if args.mode == "preflight":
        report = {
            "protocol_version": "g01-preflight-v1",
            "configuration_ready": not issues,
            "configuration_issues": issues,
            "model": config.model if config else None,
            "base_url": config.base_url if config else None,
            "response_format_mode": args.json_mode,
            "thinking_mode": thinking_mode,
            "max_output_tokens_per_request": args.max_tokens,
            "http_attempts_made": 0,
            **g01_request_plan(),
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = args.output_dir / "g01_preflight.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{out_path} · 配置{'待补充或修正' if issues else '已就绪'} · "
              f"本次 HTTP 请求 0 次，完整冒烟最多 {report['suite_max_http_attempts']} 次")
        return 1 if issues else 0

    if issues:
        parser.error("模型配置待补充或修正：" + ", ".join(item.get("environment_variable", item["field"]) for item in issues))

    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.mode == "smoke":
            result = run_g01_smoke_suite(
                config,
                response_format_mode=args.json_mode,
                sleep_seconds=args.sleep_seconds,
            )
            out_path = args.output_dir / "g01_smoke_report.json"
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            compat = result["compatibility"]
            suite = result["suite_metrics"]
            print(
                f"{out_path} · 连接={'通过' if compat['connection_passed'] else '失败'} · "
                f"三场景全部完成={'是' if compat['all_scenarios_completed'] else '否'} · "
                f"首轮合法引用率={compat['first_attempt_citation_valid_rate']} · "
                f"时序防泄漏={'全部通过' if compat['all_temporal_audits_passed'] else '异常'} · "
                f"{_format_known_usage(suite)}"
            )
            return 0 if (compat["connection_passed"] and compat["all_scenarios_completed"] and compat["all_temporal_audits_passed"]) else 1

        try:
            dataset, planned = _paired_inputs(args)
        except APIError as exc:
            parser.error(f"{exc.code}: {exc.message}")
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        paired_started = time.monotonic()
        matrices = {}
        for row, case in planned:
            matrix = evaluate_llm_ablation_matrix(
                case, row["trigger_event_id"],
                lambda: RunLLM(config, response_format_mode=args.json_mode),
                sleep_seconds=args.sleep_seconds,
            )
            if args.frozen_cohort is not None:
                matrix.update(case_family_id=row["case_family_id"], frozen_input_sha256=row["frozen_input_sha256"])
            matrices[row["scenario_id"]] = matrix
        paired_suite = {
            **aggregate_usage_meters(
                matrix["suite_metrics"]
                for matrix in matrices.values()
                if isinstance(matrix, dict) and "suite_metrics" in matrix
            ),
            "wall_clock_ms": round((time.monotonic() - paired_started) * 1000, 2),
        }
        out_path = args.output_dir / "llm_paired_results.json"
        payload = {
            "protocol_version": "llm-paired-batch-v1",
            "model": config.model,
            "provider": config.provider,
            "base_url": config.base_url,
            "response_format_mode": args.json_mode,
            "thinking_mode": thinking_mode,
            "prompt_version": prompt_version(args.json_mode),
            "max_output_tokens_per_request": args.max_tokens,
            "temperature": args.temperature,
            "dataset": dataset,
            "scenario_count": len(matrices),
            "suite_metrics": paired_suite,
            "matrices": matrices,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary = f"{out_path} · 已完成 {len(matrices)} 个截点的真实模型配对消融"
        if paired_suite["llm_calls"]:
            summary += f" · {_format_known_usage(paired_suite)}"
        print(summary + "。")
        return 0
    except ProviderError as exc:
        parser.exit(2, f"{exc.code}: {exc.message}\n")


if __name__ == "__main__":
    sys.exit(main())
