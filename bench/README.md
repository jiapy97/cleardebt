# 评测集说明

## 评测集版本

### v1: oss_smell_cases_v1.json
- **用例数**: 59条
- **项目**: dayjs (30条) + axios (29条)
- **规则数**: 37种
- **特点**: 初始手工挑选的评测集
- **用途**: 小规模快速验证

### v2: oss_smell_cases_v2.json ⭐ 推荐
- **用例数**: 120条
- **项目**: dayjs (51条) + axios (69条)
- **规则数**: 47种
- **特点**: 
  - 自动采样生成，覆盖更广
  - 规则分布均衡（每规则最多5条）
  - 包含 CODE_SMELL (115条) + BUG (5条)
  - 种子固定(seed=42)，结果可复现
- **用途**: 正式评测和对比实验

## 快速开始

### 1. 生成或更新评测集

```bash
# 预览采样结果（不生成文件）
.venv/bin/python bench/generate_cases.py --preview

# 生成120条用例（默认）
.venv/bin/python bench/generate_cases.py

# 自定义参数
.venv/bin/python bench/generate_cases.py \
  --target 150 \
  --per-rule-max 6 \
  --out bench/oss_smell_cases_v3.json
```

### 2. 运行评测

```bash
# 使用v2评测集运行对比评测（推荐）
BENCH_CASE_FILE=bench/oss_smell_cases_v2.json \
  .venv/bin/python bench/run_autonomous_compare.py --per-project 30

# 或者修改脚本中的 CASES 变量指向 v2
# 然后直接运行
.venv/bin/python bench/run_autonomous_compare.py --per-project 30
```

### 3. 查看结果

```bash
# 评测结果保存在
ls -lh var/bench/

# 查看最新的评测报告
cat var/bench/autonomous-compare-*.json | tail -1 | jq '.summary'
```

## 评测指标

每次评测会收集以下指标：

### 成功率指标
- `valid_pairs`: 有效配对数（通过所有校验）
- `fixed_l1`: 固定流程达到L1的数量
- `agent_l1`: 自主Agent达到L1的数量
- **修复成功率** = L1数量 / 有效配对数

### 验证指标
- `rescan_ok`: 重扫通过（原问题消失）
- `rescan_removed`: 消失的问题列表
- `rescan_added`: 引入的新问题列表
- `tests_passed`: 测试是否通过
- `tests_skipped`: 是否跳过测试

### 成本和耗时指标
- `agent_tool_calls`: Agent工具调用总次数
- `agent_reported_tokens`: Agent消耗的token总数
- `agent_seconds`: Agent总耗时（秒）
- `fixed_seconds`: 固定流程总耗时（秒）

### 详细追踪
- `patches`: 提交的补丁数量
- `full_checks`: 完整检查次数
- `attempts`: 重试次数
- `base_commit`: 代码库SHA（确保版本一致）

## 采样策略

`generate_cases.py` 使用以下策略确保评测集质量：

1. **过滤**: 只选择AI可修复的告警（排除机械改写）
2. **均衡**: 每个规则最多采样N条（默认5条），避免某些规则过度代表
3. **随机**: 使用固定种子(seed=42)随机打乱，确保可复现
4. **多样性**: 覆盖尽可能多的不同规则类型

## 扩展评测集

### 添加新项目

1. 在Sonar中扫描新项目
2. 在控制台绑定项目（只读模式）
3. 更新 `oss_smell_cases_v1.json` 的 `repos` 字段
4. 运行 `generate_cases.py` 重新生成

示例：
```json
"repos": {
  "bench-dayjs": {
    "url": "https://github.com/iamkun/dayjs",
    "sha": "436bde0bcded312781cbe45dc2b0ef079a36d8e3",
    "gate": "full"
  },
  "bench-lodash": {
    "url": "https://github.com/lodash/lodash",
    "sha": "...",
    "gate": "rescan-only"
  }
}
```

### 增加用例数量

```bash
# 生成200条用例
.venv/bin/python bench/generate_cases.py --target 200 --per-rule-max 8
```

## 限制和注意事项

1. **仓库版本冻结**: 评测使用固定的commit SHA，确保可复现
2. **只读模式**: 评测项目必须设置为只读，防止意外修改
3. **测试闸门**: 
   - dayjs: 完整测试+覆盖率检查
   - axios: 仅Sonar重扫（测试需要外部服务）
4. **不创建MR**: 评测只调用 `execute()`，不会开merge request
5. **资源消耗**: 每条用例会调用Sonar API重扫，注意API限流

## 下一步改进

- [ ] 增加3-4个新开源项目（目标：4-6个项目）
- [ ] 扩展到150-200条用例
- [ ] 添加安全漏洞类型（VULNERABILITY）的用例
- [ ] 支持Python/Java项目的评测
- [ ] 添加人工采纳率追踪（PR合并统计）
- [ ] 创建可视化Dashboard展示成功率趋势
