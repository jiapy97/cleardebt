from bench.run_autonomous_compare import selected_cases, valid_pair


def _arm(level: str, skipped: bool) -> dict:
    return {
        "status": "completed", "action": "start", "level": level,
        "base_commit": "abc123", "tests_skipped": skipped,
        "rescan_ok": level == "L1",
    }


def test_pair_stays_valid_when_fixed_fails_before_the_test_gate():
    pair = {
        "gate": "rescan-only",
        "fixed": {**_arm("L3", False), "fix_method": "llm"},
        "agent": {**_arm("L1", True), "fix_method": "agent"},
    }
    assert valid_pair(pair, "abc123")


def test_l1_must_have_the_configured_test_gate_result():
    pair = {
        "gate": "full",
        "fixed": {**_arm("L1", False), "fix_method": "llm"},
        "agent": {**_arm("L1", True), "fix_method": "agent"},
    }
    assert not valid_pair(pair, "abc123")


def test_case_range_keeps_the_frozen_order_in_each_project():
    manifest = {
        "repos": {"a": {}, "b": {}},
        "issues": [
            {"project": project, "rule": "javascript:S2486", "path": f"src/{number}.js"}
            for project in ("a", "b") for number in (1, 2, 3)
        ],
    }
    assert [(x["project"], x["path"]) for x in selected_cases(manifest, 3, 2)] == [
        ("a", "src/2.js"), ("a", "src/3.js"),
        ("b", "src/2.js"), ("b", "src/3.js"),
    ]
