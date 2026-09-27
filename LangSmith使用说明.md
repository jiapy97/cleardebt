# 测试 LangSmith 与真实 Agent

## ✅ LangSmith 已成功接入

环境变量已配置，测试脚本已验证连接成功。

## 🚀 运行真实 Agent 并查看 Trace

### 方式1：使用脚本（推荐）

```bash
cd /Users/perry/agent项目
chmod +x test_agent_with_langsmith.sh
./test_agent_with_langsmith.sh
```

### 方式2：手动运行

```bash
cd /Users/perry/agent项目

# 1. 加载环境变量
export $(cat .env | xargs)

# 2. 运行 Agent（test2/3/4 有 token 可以实际修复）
.venv/bin/python scripts/run_issue.py javascript:S1854 test2

# 或者
.venv/bin/python scripts/run_issue.py javascript:S1854 test3
```

## 📊 在 LangSmith 查看 Trace

1. 访问：https://smith.langchain.com
2. 选择项目：`cleardebt-dev`
3. 查看最新的 trace

你会看到完整的调用链：

```
Agent Session
├─ agent_model (选择工具)
│  ├─ Input: 告警信息 + 可用工具列表
│  ├─ LLM Call: deepseek-flash
│  │  ├─ Prompt tokens: ~1200
│  │  ├─ Completion tokens: ~50
│  │  └─ Duration: ~2秒
│  └─ Output: {"tool": "search_repo", "args": {...}}
│
├─ tool:search_repo
│  ├─ Input: 搜索参数
│  ├─ Duration: 0.5秒
│  └─ Output: 搜索结果
│
├─ agent_model (下一步)
│  └─ LLM Call: deepseek-flash
│
├─ tool:read_file
│  ├─ Input: 文件路径和行号
│  └─ Output: 文件内容 + SHA-256
│
├─ agent_model (生成补丁)
│  └─ LLM Call: deepseek-flash
│
└─ tool:apply_patch
   ├─ Input: 补丁内容
   ├─ Duration: ~80秒
   └─ run_checks: full
      ├─ rescan (65秒)
      └─ tests (15秒)
```

## 🔍 在 LangSmith 中的分析功能

### 1. 查看单次运行详情

点击任一 trace，查看：
- 每一步的输入输出
- 每一步的耗时
- LLM 的 token 消耗
- 完整的调用栈

### 2. 过滤和搜索

使用 Filters：
```
metadata.rule = "javascript:S1854"
metadata.project = "test2"
metadata.level = "L1"
```

### 3. 聚合分析

按规则聚合：
- 成功率（L1 比例）
- 平均耗时
- 平均 token 消耗
- 失败原因分布

### 4. 性能优化

找到最慢的步骤：
- 按 Duration 排序
- 查看 rescan 和 tests 耗时
- 优化瓶颈环节

## 📈 运行评测并上报

```bash
cd /Users/perry/agent项目

# 1. 加载环境变量
export $(cat .env | xargs)

# 2. 可选：切换到benchmark项目
export LANGCHAIN_PROJECT=cleardebt-benchmark

# 3. 运行评测（所有 trace 自动上报）
.venv/bin/python bench/run_autonomous_compare.py --per-project 10

# 4. 在 LangSmith 查看
# - 120条用例的完整trace
# - 按规则聚合成功率
# - 按项目分析性能
```

## 💡 LangSmith 的高级功能

### Playground

在 LangSmith Playground 中：
1. 选择一个 trace
2. 点击 "Open in Playground"
3. 修改 prompt 或参数
4. 重新运行看效果
5. 对比不同版本

### Dataset 和 Evaluators

```python
# 创建 dataset
from langsmith import Client
client = Client()

# 上传评测用例
dataset = client.create_dataset("cleardebt-test-cases")
for case in test_cases:
    client.create_example(
        inputs={"rule": case.rule, "project": case.project},
        outputs={"expected_level": "L1"},
        dataset_id=dataset.id
    )

# 运行评估
from langsmith import evaluate

def check_success(run, example):
    return {"score": 1 if run.outputs["level"] == "L1" else 0}

evaluate(
    lambda inputs: run_agent(**inputs),
    data=dataset,
    evaluators=[check_success]
)
```

## ⚠️ 注意事项

### 1. API Key 安全

- ✅ .env 文件已加入 .gitignore
- ❌ 不要把 API key 提交到代码库
- ❌ 不要在日志中打印 API key

### 2. Trace 数量控制

当前配置会上报所有 trace，如果需要控制：

```bash
# 只在开发时启用
export LANGCHAIN_TRACING_V2=false  # 关闭

# 或采样（只trace 10%）
export LANGCHAIN_TRACING_SAMPLING_RATE=0.1
```

### 3. 隐私保护

如果担心代码内容泄露：

```bash
# 隐藏输入输出
export LANGCHAIN_HIDE_INPUTS=true
export LANGCHAIN_HIDE_OUTPUTS=true
```

### 4. 不同环境

```bash
# 开发环境
export LANGCHAIN_PROJECT=cleardebt-dev

# 评测环境
export LANGCHAIN_PROJECT=cleardebt-benchmark

# 生产环境（如果需要）
export LANGCHAIN_PROJECT=cleardebt-production
```

## 📊 预期数据量

### 日常开发
- 每次运行 Agent: 1 trace
- 每天开发测试: ~10 traces
- 每月: ~300 traces

### 评测
- 120条评测集: 240 traces（固定 + Agent）
- 每月运行1次: 240 traces

### 总计
- 月均: ~540 traces
- 免费额度: 5000 traces/月
- ✅ 完全够用

## 🎓 学习资源

- 官方文档: https://docs.smith.langchain.com
- 视频教程: https://www.youtube.com/langchain
- 示例项目: https://github.com/langchain-ai/langsmith-cookbook

## 💪 面试时的说法

> "我们接入了 LangSmith 做全链路可观测性。每个 Agent 会话都有完整的 
> trace，可以看到每一步的输入输出、耗时和 token 消耗。我们的 120 条
> 评测集每次运行都会自动上报，可以在 LangSmith 按规则聚合分析成功率、
> 性能瓶颈和 token 消耗趋势。
> 
> 最有用的是快速定位失败原因：如果某个规则的成功率突然下降，我可以
> 立即在 LangSmith 看到是哪一步出问题了，是 LLM 选错了工具，还是
> rescan 超时，或是测试失败。这比看日志快多了。"

---

## ✅ 总结

✅ LangSmith 已完全接入（零代码改动）  
✅ 环境变量已配置（.env 文件）  
✅ 测试脚本验证成功  
✅ 可随时运行真实 Agent 并查看 trace  
✅ 可运行评测并聚合分析  

**现在运行上面的命令，去 LangSmith 看你的第一个真实 Agent trace 吧！** 🚀
