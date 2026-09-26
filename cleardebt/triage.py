"""Triage tiers for one issue from Sonar's own repair signals.

An authorized AI CodeFix list, when configured, controls exact rule keys.
Otherwise an issue needs Sonar's own quickFixAvailable flag. SCA dependency
upgrades and Sonar's secrets repository have their own routes: the AI CodeFix
list carries no secrets:* keys, but the fix prompt handles hard-coded secrets.

Tiers: dependency (upgrade a package), rewrite (deterministic JS/TS edit first,
model as fallback), llm (model patch), skip (not repairable), unsupported
(language the agent has not onboarded).
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


REPAIR_TIERS = frozenset({"dependency", "rewrite", "llm"})
TIER_LABELS = {
    "dependency": "依赖升级",
    "rewrite": "规则改写",
    "llm": "AI 修复",
    "skip": "不修",
    "unsupported": "语言未接入",
}
# Checkpoints and snapshots written before the rename carry letter tiers.
_LEGACY_TIERS = {"A": "dependency", "B": "llm", "C": "skip", "unknown": "unsupported"}
_ROUTE = {"rewrite": "code", "llm": "code"}


def normalize_tier(tier: str | None) -> str:
    return _LEGACY_TIERS.get(tier or "", tier or "")


def same_route(old: str | None, new: str | None) -> bool:
    """rewrite and llm run the same graph path (rewrite only tries a deterministic edit first)."""
    old, new = normalize_tier(old), normalize_tier(new)
    return _ROUTE.get(old, old) == _ROUTE.get(new, new)


def is_secrets_repo_rule(rule: str) -> bool:
    return language_of(rule) == "secrets"


def _code_tier(rule: str, path: str = "") -> str:
    from cleardebt.a_fix import has_mechanical_fix

    return "rewrite" if has_mechanical_fix(rule, path) else "llm"


def tier_for(rule: str) -> str:
    """Rule-level membership; without a list, eligibility is issue-specific."""
    if is_sca_rule(rule):
        return "dependency"
    if not language_supported(rule):
        return "unsupported"
    if is_secrets_repo_rule(rule):
        return "llm"
    return _code_tier(rule) if listed(rule) is True else "skip"


def tier_for_issue(issue: dict) -> str:
    """One issue's tier, shared by the backlog and the execution graph."""
    rule = issue.get("rule") or ""
    if is_sca_rule(rule):
        return "dependency"
    if not language_supported(rule):
        return "unsupported"
    if is_secrets_repo_rule(rule):
        return "llm"
    in_list = listed(rule)
    eligible = in_list if in_list is not None else issue.get("quick_fix") is True
    return _code_tier(rule, issue.get("path") or "") if eligible else "skip"


def issue_repairable(issue: dict) -> bool:
    # Recomputed from the rule: persisted snapshots can carry a stale tier.
    return tier_for_issue(issue) in REPAIR_TIERS


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
    return tier_for(rule) in REPAIR_TIERS
