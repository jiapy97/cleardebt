"""Rule tiers for one issue. The model does not choose the tier.

Source of truth is the Sonar server (see cleardebt.rules): thousands of
rules with severity/type, refreshed live. the rule_pins table holds Chinese labels only; tiers are always derived
from Sonar signals by the policy below. Only javascript / typescript /
python / java / csharp / secrets prefixes.
"""

import re

from cleardebt.languages import language_of, language_supported
from cleardebt.rules import lookup, pins, policy_tier
from cleardebt.sca import SCA_RULE, is_sca_rule


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
    return {"A": "maintainability", "B": "reliability", "C": "maintainability"}.get(tier_for(rule), "unknown")


def _secret_rule(rule: str) -> bool:
    """Hard-coded credentials: Sonar's own 'secrets' repo, or the classic
    S2068 credential rule (which lives in the language repos)."""
    return language_of(rule) == "secrets" or rule_number(rule) == "S2068"


def is_secret_rule(rule: str) -> bool:
    return _secret_rule(rule)


_EFFORT = re.compile(r"(\d+)\s*(min|h|d)", re.IGNORECASE)


def parse_effort(value) -> float | None:
    """Sonar reports remediation cost as '5min' / '2h' / '1d'. → minutes."""
    from cleardebt.rules import parse_effort as _shared

    return _shared(value)


def sonar_tier(issue: dict) -> str:
    """Tier from Sonar's own issue signals only — no hand-written rule list.

    Signals: type, severity, impacts (Clean Code quality+severity), effort
    (SQALE cost), quickFixAvailable. Security is always C; anything Sonar
    rates HIGH-impact, informational, or expensive (>30min) is left to
    humans; LOW-impact quick-fixable smells are the agent's sweet spot.
    """
    kind = (issue.get("sonar_type") or "").upper()
    severity = (issue.get("sonar_severity") or "").upper()
    impacts = issue.get("sonar_impacts") or []
    quality = {str((i or {}).get("softwareQuality") or "").upper() for i in impacts}
    impact_sev = {str((i or {}).get("severity") or "").upper() for i in impacts}
    if kind in {"VULNERABILITY", "SECURITY_HOTSPOT"} or "SECURITY" in quality:
        return "A" if _secrets_carveout() else "C"
    effort = parse_effort(issue.get("sonar_effort"))
    if effort is not None and effort > 30:
        return "C"
    if kind == "BUG":
        if severity in {"BLOCKER", "CRITICAL"} or "HIGH" in impact_sev:
            return "C"
        return "B"
    if kind == "CODE_SMELL":
        if "INFO" in impact_sev or "HIGH" in impact_sev:
            return "C"
        if "LOW" in impact_sev:
            return "A"
        return "A" if issue.get("quick_fix") else "B"
    return "unknown"


def _secrets_carveout() -> bool:
    """Hard-coded-credential rules are VULNERABILITY in Sonar → C by default.

    Rotating a leaked secret is a human job, so pure alignment stops here.
    Set CLEARDEBT_FIX_SECRETS=1 to let the agent rewrite them to env
    placeholders (the file change is still gated by rescan + tests).
    """
    import os

    return os.environ.get("CLEARDEBT_FIX_SECRETS", "").strip().lower() in {"1", "true", "yes"}


def tier_for(rule: str) -> str:
    """Rule-level tier, computed from Sonar's rule metadata only.

    No curated list anymore: the pins table keeps Chinese labels, but tiers
    are 100% derived (see sonar_tier for the issue-level twin).
    """
    if is_sca_rule(rule):
        return "A"
    if not language_supported(rule):
        return "unknown"
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
    return language_of(rule) == "secrets" and _secrets_carveout()
