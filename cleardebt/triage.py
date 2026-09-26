"""Rule tiers for one issue. Sonar repair eligibility uses exact list keys.

Without a configured AI CodeFix list, no Sonar issue is repairable. SCA
dependency upgrades have their own route.
"""

import re

from cleardebt.ai_codefix_rules import listed
from cleardebt.languages import language_of, language_supported
from cleardebt.rules import lookup, pins
from cleardebt.sca import is_sca_rule


def rule_number(rule: str) -> str:
    return rule.split(":")[-1]


def problem_surface(rule: str) -> str:
    """Coarse surface: maintainability | reliability | security | secrets | sca.

    Read from Sonar's own impacts (softwareQuality), not a hand-written list.
    """
    if is_sca_rule(rule):
        return "sca"
    if is_secret_rule(rule):
        return "secrets"
    meta = lookup(rule) or {}
    qualities = {str((i or {}).get("softwareQuality") or "").upper() for i in (meta.get("impacts") or [])}
    if "SECURITY" in qualities:
        return "security"
    if (meta.get("type") or "").upper() == "BUG" or "RELIABILITY" in qualities:
        return "reliability"
    if "MAINTAINABILITY" in qualities:
        return "maintainability"
    return "unknown"


def _secret_rule(rule: str) -> bool:
    """Hard-coded credentials: Sonar's own 'secrets' repo, or the classic
    S2068 credential rule (which lives in the language repos)."""
    return language_of(rule) == "secrets" or rule_number(rule) == "S2068"


def is_secret_rule(rule: str) -> bool:
    return _secret_rule(rule)


def tier_for(rule: str) -> str:
    """Listed Sonar rules use the model path; all other Sonar rules stop."""
    if is_sca_rule(rule):
        return "A"
    if not language_supported(rule):
        return "unknown"
    return "B" if listed(rule) is True else "C"


def tier_for_issue(issue: dict) -> str:
    """One issue's tier, shared by the backlog and the execution graph."""
    return tier_for(issue.get("rule") or "")


def issue_repairable(issue: dict) -> bool:
    # Persisted snapshots and resumed graph states can carry an old A/B tier.
    return tier_for_issue(issue) in {"A", "B"}


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
    return tier_for(rule) in {"A", "B"}
