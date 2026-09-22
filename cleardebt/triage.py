"""Rule tiers for one issue. The model does not choose the tier.

Keys are Sonar rule numbers. javascript:S1128 and typescript:S1128 are the same rule.
"""

# Deterministic edits. The same number applies to JavaScript and TypeScript.
A_RULES = {
    "S1128": "未使用的 import",
    "S1481": "未使用的变量",
    "S1854": "无用赋值",
    "S1656": "变量赋给自己",
    "S905": "没有作用的表达式",
    "S3923": "两个分支完全一样",
    "S1862": "后面的条件永远到不了",
    "S1871": "这个分支和前面一模一样",
}

# The model proposes a snippet. The gates still decide the level.
B_RULES = {
    "S6679": "判断 NaN 不要写成自己和自己比较",
}

# Do not edit. Record the reason.
C_RULES = {
    "S2068": "硬编码密钥",
    "S3649": "SQL 注入",
    "S3776": "认知复杂度，属于大重构",
    "S1186": "空函数不自动填实现",
    "S1135": "TODO 不自动完成",
    "S3516": "函数总是返回同一个值，要人决定",
    "S2301": "用布尔参数决定走哪条路，要人拆开",
}


def rule_number(rule: str) -> str:
    return rule.split(":")[-1]


def tier_for(rule: str) -> str:
    number = rule_number(rule)
    if number in A_RULES:
        return "A"
    if number in B_RULES:
        return "B"
    if number in C_RULES:
        return "C"
    return "unknown"


def describe(rule: str) -> str:
    number = rule_number(rule)
    return A_RULES.get(number) or B_RULES.get(number) or C_RULES.get(number) or number
