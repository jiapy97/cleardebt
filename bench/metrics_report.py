#!/usr/bin/env python3
"""Generate a comprehensive metrics report with detailed analysis."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def analyze_detailed_results() -> None:
    """Analyze detailed benchmark results."""
    result_dir = ROOT / "var" / "bench"

    if not result_dir.exists():
        print("错误: 评测结果目录不存在")
        return

    all_pairs = []
    for file in result_dir.glob("autonomous-compare-*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            all_pairs.extend(data.get("pairs", []))
        except (json.JSONDecodeError, KeyError):
            continue

    valid_pairs = [pair for pair in all_pairs if pair.get("valid")]

    print("=" * 80)
    print("📊 四大核心指标详细报告")
    print("=" * 80)
    print(f"\n数据来源: {len(valid_pairs)} 个有效配对")
    print(f"(从 {len(all_pairs)} 个总配对中筛选)")

    # 1. 修复成功率
    print("\n" + "─" * 80)
    print("1️⃣  修复成功率 - 重新扫描后问题消失")
    print("─" * 80)

    fixed_rescan_ok = sum(1 for p in valid_pairs if p.get("fixed", {}).get("rescan_ok") is True)
    agent_rescan_ok = sum(1 for p in valid_pairs if p.get("agent", {}).get("rescan_ok") is True)

    print(f"\n固定AI修复:")
    print(f"  ✓ 成功: {fixed_rescan_ok}/{len(valid_pairs)} ({fixed_rescan_ok/len(valid_pairs)*100:.1f}%)")
    print(f"  ✗ 失败: {len(valid_pairs) - fixed_rescan_ok}/{len(valid_pairs)} ({(len(valid_pairs)-fixed_rescan_ok)/len(valid_pairs)*100:.1f}%)")

    print(f"\n自主Agent:")
    print(f"  ✓ 成功: {agent_rescan_ok}/{len(valid_pairs)} ({agent_rescan_ok/len(valid_pairs)*100:.1f}%)")
    print(f"  ✗ 失败: {len(valid_pairs) - agent_rescan_ok}/{len(valid_pairs)} ({(len(valid_pairs)-agent_rescan_ok)/len(valid_pairs)*100:.1f}%)")

    print(f"\n对比: 自主Agent比固定流程多成功 {agent_rescan_ok - fixed_rescan_ok} 个案例")

    # 2. 编译和测试通过率
    print("\n" + "─" * 80)
    print("2️⃣  编译和测试通过率 - 补丁没有破坏功能")
    print("─" * 80)

    # 统计测试情况
    fixed_test_passed = sum(1 for p in valid_pairs if p.get("fixed", {}).get("tests_passed") is True)
    fixed_test_skipped = sum(1 for p in valid_pairs if p.get("fixed", {}).get("tests_skipped") is True)
    fixed_test_failed = len(valid_pairs) - fixed_test_passed - fixed_test_skipped

    agent_test_passed = sum(1 for p in valid_pairs if p.get("agent", {}).get("tests_passed") is True)
    agent_test_skipped = sum(1 for p in valid_pairs if p.get("agent", {}).get("tests_skipped") is True)
    agent_test_failed = len(valid_pairs) - agent_test_passed - agent_test_skipped

    print(f"\n固定AI修复:")
    print(f"  ✓ 测试通过: {fixed_test_passed} ({fixed_test_passed/len(valid_pairs)*100:.1f}%)")
    print(f"  ⊝ 测试跳过: {fixed_test_skipped} ({fixed_test_skipped/len(valid_pairs)*100:.1f}%)")
    print(f"  ✗ 测试失败: {fixed_test_failed} ({fixed_test_failed/len(valid_pairs)*100:.1f}%)")
    print(f"  通过率: {(fixed_test_passed + fixed_test_skipped)/len(valid_pairs)*100:.1f}%")

    print(f"\n自主Agent:")
    print(f"  ✓ 测试通过: {agent_test_passed} ({agent_test_passed/len(valid_pairs)*100:.1f}%)")
    print(f"  ⊝ 测试跳过: {agent_test_skipped} ({agent_test_skipped/len(valid_pairs)*100:.1f}%)")
    print(f"  ✗ 测试失败: {agent_test_failed} ({agent_test_failed/len(valid_pairs)*100:.1f}%)")
    print(f"  通过率: {(agent_test_passed + agent_test_skipped)/len(valid_pairs)*100:.1f}%")

    # 3. 新问题引入率
    print("\n" + "─" * 80)
    print("3️⃣  新问题引入率 - 修一个问题带出几个新问题")
    print("─" * 80)

    print("\n说明: 此指标需要从detailed checkpoint中获取rescan_added数据")
    print("当前数据中没有记录新问题数量，建议在下次评测中添加此字段")
    print("\n替代指标: L1成功的案例应该没有引入新问题（因为通过了rescan验证）")

    fixed_l1 = sum(1 for p in valid_pairs if p.get("fixed", {}).get("level") == "L1")
    agent_l1 = sum(1 for p in valid_pairs if p.get("agent", {}).get("level") == "L1")

    print(f"\n固定AI修复:")
    print(f"  L1成功（无新问题）: {fixed_l1}/{len(valid_pairs)} ({fixed_l1/len(valid_pairs)*100:.1f}%)")
    print(f"  可能有新问题: {len(valid_pairs) - fixed_l1}")

    print(f"\n自主Agent:")
    print(f"  L1成功（无新问题）: {agent_l1}/{len(valid_pairs)} ({agent_l1/len(valid_pairs)*100:.1f}%)")
    print(f"  可能有新问题: {len(valid_pairs) - agent_l1}")

    # 4. 单次修复成本和耗时
    print("\n" + "─" * 80)
    print("4️⃣  单次修复成本和耗时 - token花费、时间")
    print("─" * 80)

    fixed_seconds = [p.get("fixed", {}).get("seconds") for p in valid_pairs if p.get("fixed", {}).get("seconds")]
    agent_seconds = [p.get("agent", {}).get("seconds") for p in valid_pairs if p.get("agent", {}).get("seconds")]
    agent_tokens = [p.get("agent", {}).get("reported_tokens") for p in valid_pairs if p.get("agent", {}).get("reported_tokens")]
    agent_tool_calls = [p.get("agent", {}).get("tool_calls") for p in valid_pairs if p.get("agent", {}).get("tool_calls")]

    print(f"\n⏱️  耗时统计:")
    print(f"\n固定AI修复:")
    if fixed_seconds:
        print(f"  平均: {sum(fixed_seconds)/len(fixed_seconds):.1f} 秒")
        print(f"  最短: {min(fixed_seconds):.1f} 秒")
        print(f"  最长: {max(fixed_seconds):.1f} 秒")

    print(f"\n自主Agent:")
    if agent_seconds:
        print(f"  平均: {sum(agent_seconds)/len(agent_seconds):.1f} 秒")
        print(f"  最短: {min(agent_seconds):.1f} 秒")
        print(f"  最长: {max(agent_seconds):.1f} 秒")

    print(f"\n💰 Token成本统计 (仅自主Agent):")
    if agent_tokens:
        print(f"  平均: {sum(agent_tokens)/len(agent_tokens):.0f} tokens")
        print(f"  最少: {min(agent_tokens)} tokens")
        print(f"  最多: {max(agent_tokens)} tokens")
        print(f"  总计: {sum(agent_tokens)} tokens")

        # 估算成本 (以DeepSeek为例: $0.27/1M tokens)
        total_cost = sum(agent_tokens) / 1_000_000 * 0.27
        avg_cost = total_cost / len(agent_tokens)
        print(f"\n  估算成本 (DeepSeek定价):")
        print(f"    单次平均: ${avg_cost:.4f}")
        print(f"    总计: ${total_cost:.2f}")

    print(f"\n🔧 工具调用统计 (仅自主Agent):")
    if agent_tool_calls:
        print(f"  平均: {sum(agent_tool_calls)/len(agent_tool_calls):.1f} 次")
        print(f"  最少: {min(agent_tool_calls)} 次")
        print(f"  最多: {max(agent_tool_calls)} 次")

    # 综合对比
    print("\n" + "=" * 80)
    print("📈 综合对比")
    print("=" * 80)

    print(f"\n【成功率对比】")
    print(f"  修复成功率: 自主Agent {agent_rescan_ok/len(valid_pairs)*100:.1f}% vs 固定流程 {fixed_rescan_ok/len(valid_pairs)*100:.1f}%")
    print(f"  L1成功率:   自主Agent {agent_l1/len(valid_pairs)*100:.1f}% vs 固定流程 {fixed_l1/len(valid_pairs)*100:.1f}%")

    print(f"\n【成本对比】")
    if fixed_seconds and agent_seconds:
        print(f"  平均耗时: 自主Agent {sum(agent_seconds)/len(agent_seconds):.1f}秒 vs 固定流程 {sum(fixed_seconds)/len(fixed_seconds):.1f}秒")
    if agent_tokens:
        print(f"  平均Token: 自主Agent {sum(agent_tokens)/len(agent_tokens):.0f} (固定流程未记录)")

    print(f"\n【自主Agent优势】")
    print(f"  ✓ 修复成功率提升: +{(agent_rescan_ok - fixed_rescan_ok)/len(valid_pairs)*100:.1f}%")
    print(f"  ✓ L1成功率提升: +{(agent_l1 - fixed_l1)/len(valid_pairs)*100:.1f}%")
    if agent_seconds and fixed_seconds:
        time_diff = sum(agent_seconds)/len(agent_seconds) - sum(fixed_seconds)/len(fixed_seconds)
        print(f"  ⚠️  平均耗时增加: +{time_diff:.1f}秒 ({time_diff/(sum(fixed_seconds)/len(fixed_seconds))*100:.1f}%)")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    analyze_detailed_results()
