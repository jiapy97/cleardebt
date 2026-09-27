#!/usr/bin/env python3
"""Generate expanded benchmark cases from Sonar issues.

Samples issues from configured projects, filtering to AI-repairable rules
and balancing across rule types and difficulty levels.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from cleardebt.a_fix import has_mechanical_fix
from cleardebt.issue_graph import sonar_base_url
from cleardebt.triage import tier_for_issue
from list_issues import fetch_issues, issue_path, load_token


def fetch_all_issues(token: str, projects: dict[str, dict]) -> list[dict]:
    """Fetch all issues from Sonar for the given projects."""
    all_issues = []
    for project_key in projects:
        for issue in fetch_issues(sonar_base_url(), token, project_key):
            if not issue.get("key"):
                raise ValueError(f"{project_key} 有告警缺少 Sonar key，不能生成精确用例")
            path = issue_path(issue.get("component", ""), project_key)
            all_issues.append({
                "issue_key": issue.get("key", ""),
                "project": project_key,
                "rule": issue["rule"],
                "path": path,
                "message": issue.get("message", ""),
                "severity": issue.get("severity", ""),
                "type": issue.get("type", ""),
            })
    return all_issues


def filter_ai_repairable(issues: list[dict]) -> list[dict]:
    """Filter to AI-repairable issues (not mechanical fixes)."""
    repairable = []
    for issue in issues:
        # 构造最小的state来调用tier_for_issue
        state = {
            "rule": issue["rule"],
            "path": issue["path"],
            "message": issue["message"],
            "sonar_type": issue.get("type", ""),
            "sonar_severity": issue.get("severity", ""),
            "sonar_impacts": [],
            "sonar_effort": "",
            "quick_fix": False,
        }
        tier = tier_for_issue(state)

        # 只要不是skip且不是机械改写的，就是AI修复
        if tier not in ["skip", "language_not_integrated"]:
            if not has_mechanical_fix(issue["rule"], issue["path"]):
                repairable.append(issue)

    return repairable


def sample_balanced(issues: list[dict], target: int, per_rule_max: int = 5) -> list[dict]:
    """Sample issues with balanced distribution across rules and projects.

    Strategy:
    1. Group by rule
    2. Sample at most per_rule_max from each rule
    3. Shuffle and take target count
    """
    import random
    randomizer = random.Random(42)

    # 按规则分组
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for issue in sorted(issues, key=lambda item: (item["project"], item["rule"], item["path"], item["message"], item.get("issue_key", ""))):
        by_rule[issue["rule"]].append(issue)

    # 从每个规则中采样
    sampled = []
    for rule, rule_issues in by_rule.items():
        randomizer.shuffle(rule_issues)
        sampled.extend(rule_issues[:per_rule_max])

    # 打乱并截取
    randomizer.shuffle(sampled)
    return sampled[:target]


def analyze_distribution(issues: list[dict]) -> dict[str, Any]:
    """Analyze the distribution of issues."""
    projects = Counter(issue["project"] for issue in issues)
    rules = Counter(issue["rule"] for issue in issues)
    types = Counter(issue.get("type", "UNKNOWN") for issue in issues)

    return {
        "total": len(issues),
        "projects": dict(projects),
        "unique_rules": len(rules),
        "top_rules": dict(rules.most_common(10)),
        "types": dict(types),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=120,
                        help="目标用例数量（默认120，会被采样策略调整）")
    parser.add_argument("--per-rule-max", type=int, default=5,
                        help="每个规则最多采样数量（默认5）")
    parser.add_argument("--out", type=Path, default=ROOT / "bench" / "oss_smell_cases_v3.json",
                        help="输出文件路径")
    parser.add_argument("--preview", action="store_true",
                        help="只预览分布，不生成文件")
    args = parser.parse_args()

    # 读取现有的项目配置
    v1_path = ROOT / "bench" / "oss_smell_cases_v1.json"
    if not v1_path.exists():
        parser.error(f"找不到 {v1_path}")

    v1_data = json.loads(v1_path.read_text(encoding="utf-8"))
    projects = v1_data["repos"]

    print(f"从 {len(projects)} 个项目拉取告警...")
    token = load_token(None)
    all_issues = fetch_all_issues(token, projects)

    print(f"  总共拉取: {len(all_issues)} 条告警")
    print(f"\n按项目分布:")
    for proj, count in Counter(issue["project"] for issue in all_issues).items():
        print(f"  {proj}: {count}")

    print(f"\n过滤AI可修复告警（排除机械改写）...")
    repairable = filter_ai_repairable(all_issues)
    print(f"  AI可修复: {len(repairable)} 条")

    print(f"\n分布分析:")
    dist = analyze_distribution(repairable)
    print(f"  项目分布: {dist['projects']}")
    print(f"  不同规则数: {dist['unique_rules']}")
    print(f"  类型分布: {dist['types']}")
    print(f"\nTop 10规则:")
    for rule, count in dist["top_rules"].items():
        print(f"  {rule}: {count}")

    print(f"\n采样 {args.target} 条用例（每规则最多 {args.per_rule_max} 条）...")
    sampled = sample_balanced(repairable, args.target, args.per_rule_max)

    print(f"\n最终采样: {len(sampled)} 条")
    final_dist = analyze_distribution(sampled)
    print(f"  项目分布: {final_dist['projects']}")
    print(f"  不同规则数: {final_dist['unique_rules']}")
    print(f"  类型分布: {final_dist['types']}")

    if args.preview:
        print("\n[预览模式，未生成文件]")
        return 0

    # 生成输出
    output = {
        "generated": "expanded_oss_cases_v3",
        "repos": projects,
        "count": len(sampled),
        "sampling_strategy": f"balanced: max {args.per_rule_max} per rule, seed=42",
        "issues": [
            {
                "project": issue["project"],
                "rule": issue["rule"],
                "path": issue["path"],
                "message": issue["message"],
                "issue_key": issue.get("issue_key", ""),
            }
            for issue in sampled
        ],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n✓ 已生成: {args.out}")
    print(f"  用例数: {len(sampled)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
