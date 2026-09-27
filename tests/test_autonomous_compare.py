from bench.run_autonomous_compare import CASES, case_id, resume_payload, selected_cases, valid_pair
from bench.calculate_metrics import calculate_metrics
from bench.validate_cases import validate_case_file

import json
import pytest


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


def test_legacy_cases_with_same_rule_and_path_run_once():
    issue = {"project": "a", "rule": "javascript:S2486", "path": "src/a.js", "message": "one"}
    manifest = {"repos": {"a": {}}, "issues": [issue, {**issue, "message": "two"}]}
    assert selected_cases(manifest, 10) == [issue]
    keyed = {"repos": {"a": {}}, "issues": [{**issue, "issue_key": "first"},
                                                {**issue, "issue_key": "second"}]}
    assert len(selected_cases(keyed, 10)) == 2


def test_resume_requires_an_exact_completed_prefix():
    manifest = json.loads(CASES.read_text(encoding="utf-8"))
    cases = selected_cases(manifest, 2)
    pair = {"case_id": case_id(cases[0], manifest), "project": cases[0]["project"],
            "gate": manifest["repos"][cases[0]["project"]]["gate"],
            "valid": False, "fixed": {}, "agent": {}}
    payload = {"case_file": "bench/oss_smell_cases_v3.json", "model": "test-model",
               "agent_protocol": "v6", "pairs": [pair]}
    assert resume_payload(payload, manifest, cases, "test-model") == 1
    assert payload["summary"]["attempted_pairs"] == 1
    with pytest.raises(ValueError, match="different case file"):
        resume_payload({**payload, "case_file": "other.json"}, manifest, cases, "test-model")
    with pytest.raises(ValueError, match="case 1"):
        resume_payload({**payload, "pairs": [{**pair, "case_id": "wrong"}]}, manifest, cases, "test-model")


def test_full_gate_requires_recorded_test_execution():
    fixed = {**_arm("L1", False), "fix_method": "llm", "tests_passed": True,
             "tests_executed": False, "uncovered_lines": []}
    agent = {**_arm("L1", False), "fix_method": "agent", "tests_passed": True,
             "tests_executed": True, "uncovered_lines": []}
    pair = {"gate": "full", "fixed": fixed, "agent": agent}
    assert not valid_pair(pair, "abc123")
    fixed["tests_executed"] = True
    assert valid_pair(pair, "abc123")


def test_metrics_keep_test_skips_and_missing_fields_separate():
    full = {"case_id": "a", "gate": "full", "valid": True,
            "fixed": {"level": "L3", "tests_executed": True, "tests_passed": False,
                      "rescan_executed": True, "rescan_added": [{"rule": "new"}], "reported_tokens": 8},
            "agent": {"level": "L1", "tests_executed": True, "tests_passed": True,
                      "rescan_executed": True, "rescan_added": [], "reported_tokens": 20}}
    sonar_only = {"case_id": "b", "gate": "rescan-only", "valid": True,
                  "fixed": {"level": "L1", "tests_skipped": True},
                  "agent": {"level": "L1", "tests_skipped": True}}
    metrics = calculate_metrics({"pairs": [full, sonar_only]})
    assert metrics["by_gate"]["full"]["agent_only_l1"] == 1
    assert metrics["overall"]["fixed"]["tests"] == {
        "passed": 0, "failed": 1, "skipped": 1, "not_run": 0, "unknown": 0,
    }
    assert metrics["overall"]["fixed"]["new_issues"] == {
        "observed": 1, "with_new_issues": 1, "count": 1, "rate": 1.0,
    }
    assert metrics["overall"]["fixed"]["tokens"]["observed"] == 1


def test_metrics_reject_duplicate_case_in_one_result():
    pair = {"case_id": "same", "gate": "full", "valid": False}
    with pytest.raises(ValueError, match="重复用例"):
        calculate_metrics({"pairs": [pair, pair]})


def test_metrics_distinguish_not_run_from_old_missing_data():
    pair = {"case_id": "one", "gate": "rescan-only", "valid": True,
            "fixed": {"level": "L3", "tests_executed": False},
            "agent": {"level": "L3"}}
    result = calculate_metrics({"pairs": [pair]})["overall"]
    assert result["fixed"]["tests"]["not_run"] == 1
    assert result["agent"]["tests"]["unknown"] == 1


def test_v3_manifest_rejects_duplicate_sonar_keys(tmp_path):
    issue = {"project": "a", "rule": "javascript:S2486", "path": "src/a.js",
             "message": "fix", "issue_key": "one"}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"generated": "expanded_oss_cases_v3", "repos": {"a": {}},
                                "count": 2, "issues": [issue, issue]}), encoding="utf-8")
    assert "无法与其他告警区分" in validate_case_file(path)["error"]
