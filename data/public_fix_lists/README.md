# 公开自动修复资格清单（2026-09-26 快照）

这些文件是从各产品**公开标出的修复资格**提取的规则标识，按来源单独保存。它们只是竞品能力证据，不代表 ClearDebt 的模型一定能修好，也不能直接作为 Sonar 规则的白名单：CodeQL 查询、CWE、Ruff/Biome/ESLint 规则使用不同的编号体系。

| 文件 | 数量 | 标识含义 | 修复含义 | 来源与许可 |
| --- | ---: | --- | --- | --- |
| `github_copilot_autofix-2026-09-26.json` | 461 | CodeQL 查询帮助页路径 | 官方表格的 Copilot Autofix 列标为支持 | [GitHub CodeQL 内置查询](https://docs.github.com/en/code-security/reference/code-scanning/codeql/codeql-queries/built-in-queries)，[GitHub 文档 CC BY 4.0](https://github.com/github/docs/blob/main/LICENSE) |
| `gitlab_duo_vulnerability_resolution-2026-09-26.json` | 45 | CWE 编号 | GitLab Duo Vulnerability Resolution 支持的漏洞类别 | [GitLab 支持的 CWE](https://docs.gitlab.com/user/application_security/remediate/duo/)，[GitLab 文档 CC BY-SA 4.0](https://gitlab.com/gitlab-org/gitlab/blob/master/LICENSE) |
| `ruff-2026-09-26.json` | 479 | Ruff 规则编号 | Ruff 文档标明有确定性自动修复 | [Ruff 规则](https://docs.astral.sh/ruff/rules/)，[MIT](https://github.com/astral-sh/ruff/blob/main/LICENSE) |
| `biome-2026-09-26.json` | 202 | 语言 / Biome 规则名 | Biome 文档标明有安全或不安全修复；文件内保留 `fix_safety` | [Biome 规则](https://biomejs.dev/linter/)，[MIT OR Apache-2.0](https://github.com/biomejs/biome/blob/main/packages/%40biomejs/biome/package.json) |
| `eslint_core-2026-09-26.json` | 38 | ESLint 内置规则名 | ESLint 文档的 Fix 标记；只有建议而没有自动修复的规则未计入 | [ESLint 规则](https://eslint.org/docs/latest/rules/)，[MIT](https://github.com/eslint/eslint/blob/main/LICENSE) |
| `sonar_ai_codefix-2026-09-26.json` | 2635 | Sonar 规则键 | 官方 AI CodeFix 适用规则；文档里重复列出的 7 条 `jssecurity` 只保留一次 | [SonarQube Server 2026.1](https://docs.sonarsource.com/sonarqube-server/2026.1/quality-standards-administration/managing-rules/rules-for-ai-codefix)。当日 Server 最新版与 Cloud 页面内容相同。页面未标明可复用许可 |

清单经过**提取、筛选和字段归一化**，并非各厂商发布的原始文件。各厂商没有参与或认可本快照。GitLab 文件是单独的 CC BY-SA 4.0 来源数据；其余文件按各自标注的许可使用。重新提取脚本是 [`scripts/collect_public_fix_lists.py`](../../scripts/collect_public_fix_lists.py)。运行 `python scripts/collect_public_fix_lists.py --download --input-dir /tmp/cleardebt-public-rules --output-dir data/public_fix_lists` 可重新下载官方页面并生成当日快照；不带 `--download` 则从已保存的 HTML 重建。

未收录：[Semgrep 社区规则](https://semgrep.dev/blog/2024/important-updates-to-semgrep-oss/)采用限制竞争性 SaaS 使用的规则许可；[DeepSource](https://docs.deepsource.com/docs/developers/api/issue)提供逐项的 AI Autofix 可用字段，但未找到无需认证的完整公开名单。上述来源未混入快照。
