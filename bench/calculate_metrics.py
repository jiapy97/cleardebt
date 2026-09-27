#!/usr/bin/env python3
"""Calculate core metrics from benchmark results.

Metrics:
1. 修复成功率 - 重新扫描后问题消失
2. 编译和测试通过率 - 补丁没有破坏功能
3. 新问题引入率 - 修一个问题带出几个新问题
4. 单次修复成本和耗时 - token花费、时间
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_benchmark_results(result_dir: Path) -> list[dict]:
    """Load all benchmark result files."""
    if not result_dir.exists():
        return []

    results = []
    for file in result_dir.glob("autonomous-compare-*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            results.append(data)
        except (json.JSONDecodeError, KeyError):
            continue

    return results


def calculate_metrics(results: list[dict]) -> dict[str, Any]:
    """Calculate core metrics from benchmark results."""
    all_pairs = []
    for result in results:
        all_pairs.extend(result.get("pairs", []))

    # 只统计有效配对
    valid_pairs = [pair for pair in all_pairs if pair.get("valid")]

    if not valid_pairs:
        return {
            "total_pairs": len(all_pairs),
            "valid_pairs": 0,
            "error": "没有有效的配对数据",
        }

    # 1. 修复成功率 - rescan_ok=True
    fixed_rescan_ok = sum(
        1 for pair in valid_pairs
        if pair.get("fixed", {}).get("rescan_ok") is True
    )
    agent_rescan_ok = sum(
        1 for pair in valid_pairs
        if pair.get("agent", {}).get("rescan_ok") is True
    )

    # 2. 编译和测试通过率 - tests_passed=True (跳过的不算失败)
    fixed_tests_passed = sum(
        1 for pair in valid_pairs
        if pair.get("fixed", {}).get("tests_passed") is True
        or pair.get("fixed", {}).get("tests_skipped") is True
    )
    agent_tests_passed = sum(
        1 for pair in valid_pairs
        if pair.get("agent", {}).get("tests_passed") is True
        or pair.get("agent", {}).get("tests_skipped") is True
    )

    # 3. 新问题引入率 - 计算每个修复引入的新问题平均数
    # 注意：这个数据在pair中没有直接记录，需要从detailed results中获取
    # 暂时统计L1中rescan_ok=True的案例，它们应该没有引入新问题

    # 4. 单次修复成本和耗时
    fixed_tokens = [
        pair.get("fixed", {}).get("reported_tokens") or 0
        for pair in valid_pairs
        if pair.get("fixed", {}).get("reported_tokens")
    ]
    agent_tokens = [
        pair.get("agent", {}).get("reported_tokens") or 0
        for pair in valid_pairs
        if pair.get("agent", {}).get("reported_tokens")
    ]

    fixed_seconds = [
        pair.get("fixed", {}).get("seconds") or 0
        for pair in valid_pairs
        if pair.get("fixed", {}).get("seconds")
    ]
    agent_seconds = [
        pair.get("agent", {}).get("seconds") or 0
        for pair in valid_pairs
        if pair.get("agent", {}).get("seconds")
    ]

    # L1成功率 (同时满足rescan_ok和tests_passed)
    fixed_l1 = sum(
        1 for pair in valid_pairs
        if pair.get("fixed", {}).get("level") == "L1"
    )
    agent_l1 = sum(
        1 for pair in valid_pairs
        if pair.get("agent", {}).get("level") == "L1"
    )

    return {
        "total_pairs": len(all_pairs),
        "valid_pairs": len(valid_pairs),
        "metrics": {
            "修复成功率": {
                "definition": "重新扫描后问题消失 (rescan_ok=True)",
                "fixed": {
                    "count": fixed_rescan_ok,
                    "rate": f"{fixed_rescan_ok / len(valid_pairs) * 100:.1f}%",
                },
                "agent": {
                    "count": agent_rescan_ok,
                    "rate": f"{agent_rescan_ok / len(valid_pairs) * 100:.1f}%",
                },
            },
            "编译和测试通过率": {
                "definition": "补丁没有破坏功能 (tests_passed=True or tests_skipped=True)",
                "fixed": {
                    "count": fixed_tests_passed,
                    "rate": f"{fixed_tests_passed / len(valid_pairs) * 100:.1f}%",
                },
                "agent": {
                    "count": agent_tests_passed,
                    "rate": f"{agent_tests_passed / len(valid_pairs) * 100:.1f}%",
                },
            },
            "L1成功率": {
                "definition": "达到L1等级 (同时满足rescan_ok和tests_passed)",
                "fixed": {
                    "count": fixed_l1,
                    "rate": f"{fixed_l1 / len(valid_pairs) * 100:.1f}%",
                },
                "agent": {
                    "count": agent_l1,
                    "rate": f"{agent_l1 / len(valid_pairs) * 100:.1f}%",
                },
            },
            "单次修复成本": {
                "definition": "平均token花费",
                "fixed": {
                    "avg": f"{sum(fixed_tokens) / len(fixed_tokens):.0f}" if fixed_tokens else "N/A",
                    "min": min(fixed_tokens) if fixed_tokens else "N/A",
                    "max": max(fixed_tokens) if fixed_tokens else "N/A",
                },
                "agent": {
                    "avg": f"{sum(agent_tokens) / len(agent_tokens):.0f}" if agent_tokens else "N/A",
                    "min": min(agent_tokens) if agent_tokens else "N/A",
                    "max": max(agent_tokens) if agent_tokens else "N/A",
                },
            },
            "单次修复耗时": {
                "definition": "平均秒数",
                "fixed": {
                    "avg": f"{sum(fixed_seconds) / len(fixed_seconds):.1f}s" if fixed_seconds else "N/A",
                    "min": f"{min(fixed_seconds):.1f}s" if fixed_seconds else "N/A",
                    "max": f"{max(fixed_seconds):.1f}s" if fixed_seconds else "N/A",
                },
                "agent": {
                    "avg": f"{sum(agent_seconds) / len(agent_seconds):.1f}s" if agent_seconds else "N/A",
                    "min": f"{min(agent_seconds):.1f}s" if agent_seconds else "N/A",
                    "max": f"{max(agent_seconds):.1f}s" if agent_seconds else "N/A",
                },
            },
        },
    }


def print_metrics_report(metrics: dict) -> None:
    """Print a formatted metrics report."""
    print("=" * 80)
    print("核心指标报告")
    print("=" * 80)

    if "error" in metrics:
        print(f"\n错误: {metrics['error']}")
        print(f"总配对数: {metrics['total_pairs']}")
        print(f"有效配对数: {metrics['valid_pairs']}")
        return

    print(f"\n数据来源:")
    print(f"  总配对数: {metrics['total_pairs']}")
    print(f"  有效配对数: {metrics['valid_pairs']}")

    for metric_name, metric_data in metrics["metrics"].items():
        print(f"\n{'─' * 80}")
        print(f"【{metric_name}】")
        print(f"  定义: {metric_data['definition']}")
        print(f"\n  固定AI修复:")
        for key, value in metric_data["fixed"].items():
            print(f"    {key}: {value}")
        print(f"\n  自主Agent:")
        for key, value in metric_data["agent"].items():
            print(f"    {key}: {value}")

    print("\n" + "=" * 80)
    print("说明:")
    print("  - 修复成功率: 原问题在重扫后消失（rescan_ok=True）")
    print("  - 编译和测试通过率: 补丁通过测试或测试被跳过")
    print("  - L1成功率: 同时满足重扫和测试，可以开MR")
    print("  - 成本和耗时: 基于有数据的配对计算平均值")
    print("=" * 80)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, default=ROOT / "var" / "bench",
                        help="评测结果目录")
    parser.add_argument("--json", action="store_true",
                        help="输出JSON格式")
    args = parser.parse_args()

    if not args.result_dir.exists():
        print(f"错误: 结果目录不存在: {args.result_dir}")
        print(f"\n请先运行评测:")
        print(f"  .venv/bin/python bench/run_autonomous_compare.py --per-project 10")
        return 1

    results = load_benchmark_results(args.result_dir)

    if not results:
        print(f"错误: 在 {args.result_dir} 中没有找到评测结果文件")
        print(f"\n请先运行评测:")
        print(f"  .venv/bin/python bench/run_autonomous_compare.py --per-project 10")
        return 1

    print(f"找到 {len(results)} 个评测结果文件\n")

    metrics = calculate_metrics(results)

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print_metrics_report(metrics)

    return 0


if __name__ == "__main__":
    sys.exit(main())
