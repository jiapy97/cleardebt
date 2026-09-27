#!/usr/bin/env python3
"""Validate benchmark case files and check their readiness."""

from __future__ import annotations

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
    """Check if Sonar projects are accessible."""
    try:
        from cleardebt.controls import load_controls
        from cleardebt.issue_graph import sonar_base_url
        from list_issues import load_token, fetch_issues

        controls = load_controls()
        if not controls.get("configured"):
            print("  ⚠️  控制台未配置")
            return False

        token = load_token(None)
        base_url = sonar_base_url()

        # 尝试拉取一个项目
        try:
            issues = list(fetch_issues(base_url, token, "bench-dayjs"))
            if issues:
                return True
            return False
        except Exception as e:
            print(f"  ⚠️  Sonar连接失败: {e}")
            return False
    except Exception as e:
        print(f"  ⚠️  检查失败: {e}")
        return False


def main() -> int:
    print("=" * 60)
    print("评测集验证")
    print("=" * 60)

    case_files = [
        ROOT / "bench" / "oss_smell_cases_v1.json",
        ROOT / "bench" / "oss_smell_cases_v2.json",
    ]

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
    sonar_ok = check_sonar_availability()
    if sonar_ok:
        print("  ✓ Sonar API可访问")

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

    return 0 if all_valid else 1


if __name__ == "__main__":
    sys.exit(main())
