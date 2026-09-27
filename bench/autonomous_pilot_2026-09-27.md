# 自主 Agent 成对评测：小样本链路验证

> 历史 v4 链路试跑。当前成绩以 [v5 成对评测](autonomous_v5_report_2026-09-27.md)为准；两个版本的结果不混算。

评测日期：2026-09-27。模型：`deepseek-flash`。用例来自 [`oss_smell_cases_v1.json`](oss_smell_cases_v1.json)，只选会进入 AI 修复的告警。每条告警分别运行固定 AI 修复和自主工具循环，使用不同的新 checkpoint；两臂都只调用单告警执行器，不创建修复请求。dayjs 固定在 `436bde0bcded312781cbe45dc2b0ef079a36d8e3`，axios 固定在 `5fc40e1c7478d342ec64c4e865ed4cd1a334207c`。

| 项目 / 规则 | 检查闸门 | 固定流程 | 自主 Agent | Agent 工具调用 | Agent 用时 |
| --- | --- | --- | --- | ---: | ---: |
| dayjs / `javascript:S1940` | Sonar + 测试 + 覆盖率 | L1 | L1 | 4 | 48.1 秒 |
| dayjs / `javascript:S2486` | Sonar + 测试 + 覆盖率 | L3 | L3 | 7 | 49.4 秒 |
| axios / `javascript:S1121` | 仅 Sonar，测试跳过 | L1 | L1 | 4 | 45.9 秒 |
| axios / `javascript:S2486` | 仅 Sonar，测试跳过 | L1 | L1 | 4 | 44.5 秒 |

**有效配对 4 对：自主 Agent L1 3 条，固定流程 L1 3 条。** 两臂在这批样本上没有表现出成功数差异。自主 Agent 合计 19 次工具调用、4 个候选补丁、4 次完整检查，模型报告 token 合计 41,437；固定流程未记录可比较的 token 用量。固定流程总用时 182.5 秒，自主 Agent 总用时 187.9 秒。样本太少，不能把 3/4 外推为总体成功率。

dayjs 的 `S2486` 中，自主 Agent 提交了补丁并做了完整检查，目标告警未通过重扫；下一轮模型返回的工具调用无法解析，最终为 L3。这是一个明确的协议稳定性改进点。

原始结果保存在 `var/bench/autonomous-compare-8322a63be76f.json` 和 `var/bench/autonomous-compare-ab5810b49505.json`。第一轮有一对因匿名 Git 克隆失败而无效；第二轮只重跑这一对。两次运行各自使用新的评测标识，汇总只纳入通过模式、仓库 SHA、检查闸门和 checkpoint 校验的结果。

复现命令：

```bash
.venv/bin/python bench/run_autonomous_compare.py --per-project 2
```

脚本会产生新的模型调用与 Sonar 临时重扫，因此再次运行的结果可能因模型和服务状态而不同。
