# 成对修复评测

## 用例与判卷

当前输入是 `oss_smell_cases_v3.json`：dayjs 45 条、axios 75 条，共 120 条，48 种规则。每条用例保存 Sonar issue key 和固定仓库 SHA，因此同一文件里的多条告警可以分别执行。v1 是历史小样本；v2 虽有 120 行，但没有 issue key，按项目、规则和路径只能区分 100 条，不用于正式评测。

一条告警分别交给固定 AI 修复和自主 Agent。两臂使用同一模型、同一仓库提交、独立的新 checkpoint，顺序执行；评测不创建修复请求。只有两臂都完成，执行模式、起点、仓库 SHA 和对应检查闸门匹配时，才记为有效配对。环境或执行器错误单列无效原因；进入修复后得到 L3 则仍计入有效配对。

- **dayjs `full`**：补丁防作弊、Sonar 重扫、项目测试和改动行覆盖率。目标告警消失、没有新增告警、测试及覆盖率通过，才记 L1。
- **axios `rescan-only`**：补丁防作弊和 Sonar 重扫；测试按配置跳过。其 L1 单独报告，不能称为测试通过。

报告每个闸门的 L1 数量、Agent 独有成功和固定流程独有成功；测试状态区分实际通过、失败、跳过和未知。新增告警只在重扫确实运行时统计。token 仅在模型接口返回 usage 时统计；历史固定流程没有同口径 token，不能据此比较费用。

## 命令

```bash
# 验证当前冻结文件与 Sonar 可用性
.venv/bin/python bench/validate_cases.py

# 只查冻结文件结构
.venv/bin/python bench/validate_cases.py --offline

# 从 Sonar 重新生成含 issue key 的用例；不会调用模型
.venv/bin/python bench/generate_cases.py --target 120 --per-rule-max 5

# 新运行先从少量配对开始；默认读取 v3
.venv/bin/python bench/run_autonomous_compare.py --per-project 2

# 正式运行会调用模型与 Sonar，结果保存在 var/bench/
.venv/bin/python bench/run_autonomous_compare.py --per-project 120

# 中断后保留已完成配对，核对冻结清单前缀并从下一题续跑
CLEARDEBT_SCANNER_CPUS=2.0 .venv/bin/python bench/run_autonomous_compare.py \
  --per-project 120 --resume var/bench/autonomous-compare-RUN_ID.json

# 一次只统计一份结果；若要研究历史 v5，省略 --input 即可
.venv/bin/python bench/calculate_metrics.py --input var/bench/autonomous-compare-RUN_ID.json
.venv/bin/python bench/calculate_metrics.py --input var/bench/autonomous-compare-RUN_ID.json --json
```

`--per-project` 是每个项目内的终止序号，不是总用例数。旧文件可用 `BENCH_CASE_FILE=oss_smell_cases_v1.json` 指定，变量值只写文件名。`validate_cases.py --include-legacy --offline` 会审计 v1/v2，并明确报告 v2 的模糊重复项。

历史 v5 的 30 对试跑来自 v1，有效 27 对，详见 `autonomous_v5_report_2026-09-27.md`。v3 的结果需要重新运行；不能把不同版本或重跑记录直接相加。

## 重扫耗时

2026-09-27 的 v6 运行中，旧配置的 Sonar 重扫约 38–41 秒，其中扫描器容器本身约 35–38 秒。扫描器原先每次使用一次性容器，分析器下载缓存随容器一起丢失；续跑进程挂载持久 Docker 卷 `cleardebt-sonar-scanner-cache`，遵循 [SonarScanner CLI 官方缓存示例](https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/scanners/sonarscanner)。同时将扫描器限额从 1 CPU 提到 2 CPU。新配置首次扫描约 23 秒，缓存热后约 20 秒；这是两项调整的合并效果，不能单独归因。结果文件的 `segments` 标记配置切换位置；配对质量指标仍可合并，耗时须按段查看。

当前扫描器镜像是 `linux/amd64`，而 Docker 宿主机是 `linux/arm64`。若还需提速，可在独立试跑中比较原镜像与官方原生架构 CLI；先核对两者的规则、告警和耗时，再决定是否切换正式评测。缩小 `sonar.sources` 到单个改动文件会漏掉其他新增告警，不能用于当前完整性闸门。
