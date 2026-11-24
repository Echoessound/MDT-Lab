"""Run G01 real-LLM smoke validation or paired LLM ablation experiments (Plan G01 / G04).

Reads API key from environment variable (default: MDT_LLM_API_KEY) so secrets never
appear in shell history, manifest JSON, or reproduction artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from pydantic import SecretStr

from mdt_demo.research.experiments import load_cases
from mdt_demo.research.llm_benchmark import evaluate_llm_ablation_matrix, run_g01_smoke_suite
from mdt_demo.research.provider import RunLLM
from mdt_demo.research.provider_config import LLMConfigInput, ProviderError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="执行计划书 G01 真实模型兼容性联调或配对 LLM 消融基准（不泄露密钥）。"
    )
    parser.add_argument("--base-url", required=True, help="OpenAI 兼容服务端点，如 https://api.openai.com/v1")
    parser.add_argument("--model", required=True, help="目标模型标识")
    parser.add_argument("--provider", default="openai-compatible", help="提供方标签（仅用于记录）")
    parser.add_argument("--api-key-env", default="MDT_LLM_API_KEY", help="存放密钥的环境变量名")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json-mode", choices=["json_schema", "json_object"], default="json_schema",
                        help="结构化输出模式：默认严格 json_schema，若国产接口拒绝可显式测试 json_object")
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="相邻场景/方法组间限流间隔秒数")
    parser.add_argument("--mode", choices=["smoke", "paired"], default="smoke",
                        help="smoke: G01 三场景兼容联调；paired: 配对 B0–B3 + A1/A3/A4 消融")
    parser.add_argument("--source", choices=["seed", "tcia_nsclc_csv", "synthea_csv", "tcga_cbioportal_tsv", "research_json"],
                        default="seed")
    parser.add_argument("--input", type=Path, help="外部来源文件（paired 模式非 seed 来源必填）")
    parser.add_argument("--max-cases", type=int, default=3)
    parser.add_argument("--triggers", choices=["all", "latest"], default="latest")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        parser.exit(2, f"环境变量 {args.api_key_env} 未设置。请先在终端 export {args.api_key_env}=<your_key>。\n")

    try:
        config = LLMConfigInput(
            provider=args.provider,
            base_url=args.base_url,
            model=args.model,
            api_key=SecretStr(api_key),
            timeout_seconds=args.timeout,
            temperature=args.temperature,
            max_output_tokens=args.max_tokens,
        )
    except Exception as exc:
        parser.exit(2, f"模型参数校验失败: {exc}\n")

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
            print(
                f"{out_path} · 连接={'通过' if compat['connection_passed'] else '失败'} · "
                f"三场景全部完成={'是' if compat['all_scenarios_completed'] else '否'} · "
                f"首轮合法引用率={compat['first_attempt_citation_valid_rate']} · "
                f"时序防泄漏={'全部通过' if compat['all_temporal_audits_passed'] else '异常'}"
            )
            return 0 if (compat["connection_passed"] and compat["all_scenarios_completed"] and compat["all_temporal_audits_passed"]) else 1

        if (args.source == "seed") != (args.input is None):
            parser.error("外部来源必须提供 --input，seed 来源无需文件")
        cases, dataset = load_cases(args.source, args.input, args.max_cases)
        matrices = {}
        for case in cases:
            triggers = case.timeline if args.triggers == "all" else case.timeline[-1:]
            for event in triggers:
                sid = f"{case.case_id}:v{case.version}:{event.event_id}"
                matrices[sid] = evaluate_llm_ablation_matrix(
                    case,
                    event.event_id,
                    lambda: RunLLM(config, response_format_mode=args.json_mode),
                    sleep_seconds=args.sleep_seconds,
                )
        out_path = args.output_dir / "llm_paired_results.json"
        payload = {
            "protocol_version": "llm-paired-batch-v1",
            "model": config.model,
            "provider": config.provider,
            "base_url": config.base_url,
            "response_format_mode": args.json_mode,
            "dataset": dataset,
            "scenario_count": len(matrices),
            "matrices": matrices,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{out_path} · 已完成 {len(matrices)} 个截点的真实模型配对消融。")
        return 0
    except ProviderError as exc:
        parser.exit(2, f"{exc.code}: {exc.message}\n")


if __name__ == "__main__":
    sys.exit(main())
