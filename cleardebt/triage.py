"""Rule tiers for one issue. The model does not choose the tier.

Keys are Sonar rule numbers. javascript:S1128 and python:S1128 are the same rule.

Surfaces covered:
- Maintainability: unused / dead code / identical branches (A)
- Reliability: NaN compare (B), identical operands, empty statements (A)
- Partial security: hardcoded IP → env (A); SQL injection stays C
- Secrets: hardcoded credentials (A); Sonar `secrets:` findings (A unless C)

A/B are repaired by an LLM patch by default. A rules still have an optional
mechanical fast path when CLEARDEBT_MECHANICAL_FIX=1. C is record-only.
Only javascript / typescript / python / java / csharp / secrets prefixes.
"""

from cleardebt.languages import language_of, language_supported
from cleardebt.sca import SCA_RULE, is_sca_rule

# Repairable by LLM; optional mechanical fast path exists for these numbers.
A_RULES = {
    # Maintainability
    "S1128": "未使用的 import",
    "S1481": "未使用的变量",
    "S1854": "无用赋值",
    "S1656": "变量赋给自己",
    "S905": "没有作用的表达式",
    "S3923": "两个分支完全一样",
    "S1862": "后面的条件永远到不了",
    "S1871": "这个分支和前面一模一样",
    "S1116": "空语句",
    "S1764": "运算符两边是同一个表达式",
    # Secrets / partial security (local rewrite → env; Sonar rescan gates)
    "S2068": "硬编码密钥",
    "S1313": "硬编码 IP 地址",
    # SCA
    "UPGRADE": "按建议升依赖版本",
}

# Repairable by LLM; needs extra evidence before the prompt.
B_RULES = {
    "S6679": "判断 NaN 不要写成自己和自己比较",
}

# Do not edit. Record the reason.
C_RULES = {
    "S3649": "SQL 注入",
    "S3776": "认知复杂度，属于大重构",
    "S1186": "空函数不自动填实现",
    "S1135": "TODO 不自动完成",
    "S3516": "函数总是返回同一个值，要人决定",
    "S2301": "用布尔参数决定走哪条路，要人拆开",
}


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
    if number in B_RULES or number in {"S1764", "S1116", "S1862"}:
        return "reliability"
    if number in A_RULES or number in C_RULES:
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
    if number in C_RULES:
        return "C"
    if number in A_RULES:
        return "A"
    if number in B_RULES:
        return "B"
    if language_of(rule) == "secrets":
        return "A"
    return "unknown"


def describe(rule: str) -> str:
    if is_sca_rule(rule):
        return A_RULES.get("UPGRADE") or "按建议升依赖版本"
    number = rule_number(rule)
    if number in A_RULES:
        return A_RULES[number]
    if number in B_RULES:
        return B_RULES[number]
    if number in C_RULES:
        return C_RULES[number]
    if language_of(rule) == "secrets":
        return "硬编码密钥（Secrets）"
    return number


def llm_repairable(rule: str) -> bool:
    if is_sca_rule(rule):
        return True
    if not language_supported(rule):
        return False
    number = rule_number(rule)
    if number in C_RULES:
        return False
    if number in A_RULES or number in B_RULES:
        return True
    return language_of(rule) == "secrets"
