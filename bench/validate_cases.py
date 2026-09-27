#!/usr/bin/env python3
"""Validate benchmark case files and check their readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def validate_case_file(path: Path) -> dict:
    """Validate a benchmark case file and return statistics."""
    if not path.exists():
        return {"valid": False, "error": f"文件不存在: {path}"}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"valid": False, "error": f"JSON解析失败: {e}"}

    # 检查必需字段
    required = ["repos", "count", "issues"]
    for field in required:
        if field not in data:
            return {"valid": False, "error": f"缺少必需字段: {field}"}

    # 检查用例结构
    issues = data.get("issues", [])
    if len(issues) != data["count"]:
        return {"valid": False, "error": f"count字段({data['count']})与实际用例数({len(issues)})不符"}

    # 检查每个用例的字段
    for i, issue in enumerate(issues):
        required_fields = ["project", "rule", "path", "message"]
        for field in required_fields:
            if field not in issue:
                return {"valid": False, "error": f"用例 {i+1} 缺少字段: {field}"}
        if issue["project"] not in data["repos"]:
            return {"valid": False, "error": f"用例 {i+1} 的项目不在 repos 中"}

    identities = [((issue["project"], issue["issue_key"]) if issue.get("issue_key") else
                  (issue["project"], issue["rule"], issue["path"])) for issue in issues]
    ambiguous = len(identities) - len(set(identities))
    if ambiguous:
        return {"valid": False, "error": f"{ambiguous} 条用例无法与其他告警区分；请用 Sonar issue_key 重新生成"}
    if data.get("generated") == "expanded_oss_cases_v3" and any(not x.get("issue_key") for x in issues):
        return {"valid": False, "error": "v3 用例必须包含 Sonar issue_key"}

    # 统计信息
    from collections import Counter
    projects = Counter(item["project"] for item in issues)
    rules = Counter(item["rule"] for item in issues)

    return {
        "valid": True,
        "path": str(path.relative_to(ROOT)),
        "count": len(issues),
        "projects": dict(projects),
        "unique_rules": len(rules),
        "repos": list(data["repos"].keys()),
    }


def check_sonar_availability() -> bool:
    """Check that every frozen v3 issue still exists in its Sonar project."""
    try:
        from cleardebt.controls import load_controls
        from cleardebt.issue_graph import sonar_base_url
        from list_issues import load_token, fetch_issues, issue_path

        controls = load_controls()
        if not controls.get("configured"):
            print("  ⚠️  控制台未配置")
            return False

        token = load_token(None)
        base_url = sonar_base_url()

        manifest = json.loads((ROOT / "bench" / "oss_smell_cases_v3.json").read_text(encoding="utf-8"))
        missing = []
        for project in manifest["repos"]:
            available = {
                (row.get("key"), row.get("rule"), issue_path(row.get("component") or "", project))
                for row in fetch_issues(base_url, token, project)
            }
            for issue in manifest["issues"]:
                if issue["project"] == project and (
                    issue["issue_key"], issue["rule"], issue["path"]
                ) not in available:
                    missing.append(issue["issue_key"])
        if missing:
            print(f"  ⚠️  {len(missing)} 条冻结告警在 Sonar 中不可用；前 3 个 key: {missing[:3]}")
            return False
        print(f"  ✓ {manifest['count']} 条冻结告警均可定位")
        return True
    except Exception as e:
        print(f"  ⚠️  检查失败: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-legacy", action="store_true", help="同时审计 v1/v2 历史用例")
    parser.add_argument("--offline", action="store_true", help="只验证冻结文件，不访问 Sonar")
    args = parser.parse_args()
    print("=" * 60)
    print("评测集验证")
    print("=" * 60)

    case_files = ([ROOT / "bench" / "oss_smell_cases_v1.json",
                   ROOT / "bench" / "oss_smell_cases_v2.json"] if args.include_legacy else [])
    v3 = ROOT / "bench" / "oss_smell_cases_v3.json"
    case_files.append(v3)

    all_valid = True
    for case_file in case_files:
        print(f"\n检查: {case_file.name}")
        result = validate_case_file(case_file)

        if result["valid"]:
            print(f"  ✓ 格式有效")
            print(f"  ✓ 用例数: {result['count']}")
            print(f"  ✓ 项目数: {len(result['projects'])}")
            print(f"  ✓ 规则数: {result['unique_rules']}")
            print(f"  项目分布:")
            for proj, count in result["projects"].items():
                print(f"    - {proj}: {count} 条")
        else:
            print(f"  ✗ 验证失败: {result['error']}")
            all_valid = False

    print("\n" + "-" * 60)
    print("Sonar可用性检查")
    print("-" * 60)
    sonar_ok = True if args.offline else check_sonar_availability()
    if args.offline:
        print("  未检查（--offline）")

    print("\n" + "=" * 60)
    if all_valid and sonar_ok:
        print("✓ 所有检查通过，可以运行评测")
        print("\n推荐命令:")
        print("  .venv/bin/python bench/run_autonomous_compare.py --per-project 10")
    elif all_valid:
        print("⚠️  评测集有效，但Sonar未配置或不可访问")
    else:
        print("✗ 部分检查失败，请修复后再运行评测")
    print("=" * 60)

    return 0 if all_valid and sonar_ok else 1


if __name__ == "__main__":
    sys.exit(main())
