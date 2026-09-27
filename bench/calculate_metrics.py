#!/usr/bin/env python3
"""Report one paired repair evaluation without mixing historical reruns."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "bench" / "autonomous_v5_results.json"


def load_benchmark_results(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("请用 --input 指定单个评测 JSON 文件；不能汇总整个历史目录")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases", payload.get("pairs")), list):
        raise ValueError("评测文件缺少 cases 或 pairs 列表")
    return payload


def _case_key(pair: dict) -> tuple:
    if pair.get("case_id"):
        return (pair["case_id"],)
    return (pair.get("project"), pair.get("rule"), pair.get("path"), pair.get("gate"))


def _test_status(arm: dict) -> str:
    if arm.get("tests_skipped") is True:
        return "skipped"
    if arm.get("tests_executed") is True:
        return "passed" if arm.get("tests_passed") is True and not arm.get("uncovered_lines") else "failed"
    if arm.get("tests_executed") is False:
        return "not_run"
    return "unknown"


def _arm_metrics(pairs: list[dict], mode: str) -> dict:
    arms = [pair[mode] for pair in pairs]
    statuses = Counter(_test_status(arm) for arm in arms)
    tokens = [arm["reported_tokens"] for arm in arms
              if isinstance(arm.get("reported_tokens"), (int, float)) and arm["reported_tokens"] > 0]
    seconds = [arm["seconds"] for arm in arms if isinstance(arm.get("seconds"), (int, float))]
    known_new = [arm["rescan_added"] for arm in arms
                 if arm.get("rescan_executed") is True and isinstance(arm.get("rescan_added"), list)]
    return {
        "l1": sum(arm.get("level") == "L1" for arm in arms),
        "rescan_ok": sum(arm.get("rescan_ok") is True for arm in arms),
        "tests": {name: statuses[name] for name in ("passed", "failed", "skipped", "not_run", "unknown")},
        "new_issues": {"observed": len(known_new), "with_new_issues": sum(bool(x) for x in known_new),
                       "count": sum(len(x) for x in known_new),
                       "rate": round(sum(bool(x) for x in known_new) / len(known_new), 3) if known_new else None},
        "tokens": {"observed": len(tokens), "total": sum(tokens),
                   "mean": round(sum(tokens) / len(tokens), 1) if tokens else None},
        "seconds": {"observed": len(seconds), "total": round(sum(seconds), 1),
                    "mean": round(sum(seconds) / len(seconds), 1) if seconds else None},
    }


def _group_metrics(pairs: list[dict]) -> dict:
    n = len(pairs)
    fixed = _arm_metrics(pairs, "fixed")
    agent = _arm_metrics(pairs, "agent")
    return {
        "pairs": n,
        "fixed": fixed,
        "agent": agent,
        "both_l1": sum(p["fixed"].get("level") == p["agent"].get("level") == "L1" for p in pairs),
        "agent_only_l1": sum(p["agent"].get("level") == "L1" and p["fixed"].get("level") != "L1" for p in pairs),
        "fixed_only_l1": sum(p["fixed"].get("level") == "L1" and p["agent"].get("level") != "L1" for p in pairs),
        "neither_l1": sum(p["fixed"].get("level") != "L1" and p["agent"].get("level") != "L1" for p in pairs),
        "l1_delta_pp": round(100 * (agent["l1"] - fixed["l1"]) / n, 1) if n else None,
    }


def calculate_metrics(payload: dict) -> dict:
    cases = payload.get("cases", payload.get("pairs", []))
    keys = [_case_key(pair) for pair in cases]
    if len(keys) != len(set(keys)):
        raise ValueError("同一评测文件包含重复用例；请先审核并选定一次正式运行")
    valid = [pair for pair in cases if pair.get("valid") is True]
    invalid = [pair for pair in cases if pair.get("valid") is not True]
    by_gate = {}
    for gate in sorted({pair.get("gate") or "unknown" for pair in valid}):
        by_gate[gate] = _group_metrics([pair for pair in valid if (pair.get("gate") or "unknown") == gate])
    return {
        "source_run_id": payload.get("run_id") or payload.get("source_run_ids"),
        "protocol": payload.get("agent_protocol"),
        "model": payload.get("model"),
        "attempted_pairs": len(cases),
        "valid_pairs": len(valid),
        "invalid_reasons": dict(Counter(pair.get("exclusion") or pair.get("reason") or "未说明" for pair in invalid)),
        "overall": _group_metrics(valid),
        "by_gate": by_gate,
    }


def _rate(successes: int, total: int) -> str:
    return f"{successes}/{total} ({100 * successes / total:.1f}%)" if total else "N/A"


def format_report(metrics: dict) -> str:
    lines = [
        "# 成对修复评测报告",
        "",
        f"模型：{metrics['model'] or '未记录'}；协议：{metrics['protocol'] or '未记录'}。",
        f"预定 {metrics['attempted_pairs']} 对，有效 {metrics['valid_pairs']} 对。",
        "",
        "| 检查闸门 | 有效配对 | 固定流程 L1 | 自主 Agent L1 | Agent 独有 / 固定独有 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for gate, group in metrics["by_gate"].items():
        lines.append(f"| {gate} | {group['pairs']} | {_rate(group['fixed']['l1'], group['pairs'])} "
                     f"| {_rate(group['agent']['l1'], group['pairs'])} "
                     f"| {group['agent_only_l1']} / {group['fixed_only_l1']} |")
    lines += ["", "不同检查闸门的 L1 只在各自组内比较，不合成一个质量通过率。", ""]
    if metrics["invalid_reasons"]:
        lines.append("无效配对：" + "；".join(f"{reason} × {count}" for reason, count in metrics["invalid_reasons"].items()) + "。")
        lines.append("")
    lines += ["| 指标（有效配对） | 固定流程 | 自主 Agent |", "| --- | ---: | ---: |"]
    for label, key in (("实际测试通过", "passed"), ("实际测试失败", "failed"),
                       ("测试按配置跳过", "skipped"), ("未运行到测试阶段", "not_run"),
                       ("历史结果缺字段", "unknown")):
        lines.append(f"| {label} | {metrics['overall']['fixed']['tests'][key]} | "
                     f"{metrics['overall']['agent']['tests'][key]} |")
    for label, key in (("新增告警", "new_issues"), ("模型报告 token", "tokens"), ("耗时（秒）", "seconds")):
        fixed, agent = metrics["overall"]["fixed"][key], metrics["overall"]["agent"][key]
        if key == "new_issues":
            values = [f"{item['count']} 条；{item['with_new_issues']}/{item['observed']} 对引入" if item["observed"] else "未记录"
                      for item in (fixed, agent)]
        elif key == "tokens":
            values = [f"{item['total']}（有数据 {item['observed']} 对）" if item["observed"] else "未记录"
                      for item in (fixed, agent)]
        else:
            values = [f"{item['total']}（有数据 {item['observed']} 对）" if item["observed"] else "未记录"
                      for item in (fixed, agent)]
        lines.append(f"| {label} | {values[0]} | {values[1]} |")
    lines += ["", "历史结果缺字段时不反推测试是否执行；未运行到测试阶段的修复也不算测试失败。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="单个正式评测 JSON 文件")
    parser.add_argument("--json", action="store_true", help="输出结构化汇总")
    parser.add_argument("--out", type=Path, help="同时写入报告文件")
    args = parser.parse_args()
    try:
        metrics = calculate_metrics(load_benchmark_results(args.input))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    output = json.dumps(metrics, ensure_ascii=False, indent=2) + "\n" if args.json else format_report(metrics)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
