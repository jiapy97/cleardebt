"""Rule tiers for one issue. The model does not choose the tier.

Source of truth is the Sonar server (see cleardebt.rules): thousands of
rules with severity/type, refreshed live. rules/overrides.json pins the
curated tier + Chinese label for rules we have tuned; everything else is
graded by the automatic policy below. Only javascript / typescript /
python / java / csharp / secrets prefixes.
"""

import re

from cleardebt.languages import language_of, language_supported
from cleardebt.rules import lookup, pins, policy_tier
from cleardebt.sca import SCA_RULE, is_sca_rule


def rule_number(rule: str) -> str:
    return rule.split(":")[-1]


def problem_surface(rule: str) -> str:
    """Coarse surface: maintainability | reliability | security | secrets | sca."""
    if is_sca_rule(rule):
        return "sca"
    number = rule_number(rule)
    if language_of(rule) == "secrets" or number == "S2068":
        return "secrets"
    if number in {"S1313", "S3649"}:
        return "security"
    if tier_for(rule) == "B":
        return "reliability"
    if tier_for(rule) in {"A", "C"}:
        return "maintainability"
    return "unknown"


def is_secret_rule(rule: str) -> bool:
    return problem_surface(rule) == "secrets"


def tier_for(rule: str) -> str:
    if is_sca_rule(rule):
        return "A"
    if not language_supported(rule):
        return "unknown"
    number = rule_number(rule)
    pin = pins().get(number)
    if pin and pin.get("tier") in {"A", "B", "C"}:
        return pin["tier"]
    if language_of(rule) == "secrets":
        return "A"
    try:
        return policy_tier(lookup(rule))
    except Exception:
        return "unknown"


def _english_name(rule: str) -> str:
    try:
        meta = lookup(rule) or {}
    except Exception:
        meta = {}
    name = (meta.get("name") or "").strip()
    return name or rule_number(rule)


def describe(rule: str) -> str:
    if is_sca_rule(rule):
        return pins().get("UPGRADE", {}).get("zh") or "按建议升依赖版本"
    number = rule_number(rule)
    pin = pins().get(number)
    if pin and pin.get("zh"):
        return pin["zh"]
    if language_of(rule) == "secrets":
        return "硬编码密钥（Secrets）"
    return _english_name(rule)


_QUOTED = re.compile(r"'([^']{1,60})'|\"([^\"]{1,60})\"|`([^`]{1,60})`")
_LINE_REF = re.compile(r"\bline (\d{1,4})\b", re.IGNORECASE)


def describe_message(rule: str, message: str) -> str:
    """Chinese one-liner for the issue list: short label + key details.

    Sonar messages are English templates with embedded identifiers
    (function names, variables, line numbers). Keep those, translate the
    framing: e.g. "空函数不自动填实现（emptyHandler）".
    """
    base = describe(rule)
    text = (message or "").strip()
    if not text or text == base:
        return base
    if is_sca_rule(rule):
        return base if base in text else f"{base}：{text}"
    extras: list[str] = []
    for single, double, ticked in _QUOTED.findall(text):
        token = (single or double or ticked).strip()
        if token and token not in extras and token not in base:
            extras.append(token)
    for lineno in _LINE_REF.findall(text):
        token = f"第 {lineno} 行"
        if token not in extras:
            extras.append(token)
    if not extras:
        return base
    return f"{base}（{'、'.join(extras[:3])}）"


def llm_repairable(rule: str) -> bool:
    if is_sca_rule(rule):
        return True
    if not language_supported(rule):
        return False
    tier = tier_for(rule)
    if tier in {"A", "B"}:
        return True
    if tier == "C":
        return False
    return language_of(rule) == "secrets"
