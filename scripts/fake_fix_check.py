#!/usr/bin/env python3
"""Build three fake patches and print why each one is rejected."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cleardebt.fake_fix import review_patch

PROJECT = ROOT / "fixtures" / "toy-js" / "src"
PRICING = (PROJECT / "pricing.js").read_text(encoding="utf-8")
PRICING_TEST = (PROJECT / "pricing.test.js").read_text(encoding="utf-8")


def main() -> int:
    patches = [
        (
            "抑制注释",
            "src/pricing.js",
            PRICING,
            PRICING.replace("return qty * unit;", "return qty * unit; // NOSONAR", 1),
        ),
        (
            "改测试",
            "src/pricing.test.js",
            PRICING_TEST,
            PRICING_TEST.replace("toBe(10)", "toBe(11)", 1),
        ),
        (
            "掏空函数",
            "src/pricing.js",
            PRICING,
            PRICING.replace("  return qty * unit;\n", "", 1),
        ),
    ]
    seen = set()
    for title, path, before, after in patches:
        rejections = review_patch([(path, before, after)])
        if len(rejections) != 1:
            print(json.dumps({"title": title, "rejections": rejections}, ensure_ascii=False))
            return 1
        seen.add(rejections[0]["kind"])
        print(f"{title}：拒绝")
        print(f"  {rejections[0]['reason']}")
    expected = {"suppression", "test_file", "emptied_function"}
    if seen != expected:
        print(f"缺少拒绝类型：{expected - seen}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
