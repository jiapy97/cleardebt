# LangSmith 接入方案

## 📋 现状分析

### 当前架构
```python
# 你们现在使用
langgraph==1.2.12
langgraph-checkpoint-postgres==3.1.2

# 已有的observability
- PostgreSQL checkpoint存储
- agent_events表记录工具调用
- 活动页展示工具记录
```

### 缺少什么？
❌ 缺少完整的trace可视化  
❌ 缺少跨会话的性能分析  
❌ 缺少prompt版本管理  
❌ 缺少在线debug能力  

---

## 🎯 为什么要接入LangSmith？

### 1. 可视化Trace

**现状**：只能在活动页看工具调用列表
```
工具1: search_repo → 完成
工具2: read_file → 完成
工具3: apply_patch → 失败
```

**接入LangSmith后**：完整的调用链可视化
```
┌─ Agent Session (87.8秒)
│  ├─ agent_model (2.3秒)
│  │  └─ LLM Call: deepseek-flash (2.1秒, 1.2K tokens)
│  ├─ agent_tool: search_repo (0.5秒)
│  ├─ agent_model (1.8秒)
│  │  └─ LLM Call: deepseek-flash (1.6秒, 0.8K tokens)
│  ├─ agent_tool: read_file (0.3秒)
│  ├─ agent_model (2.5秒)
│  │  └─ LLM Call: deepseek-flash (2.3秒, 3.2K tokens)
│  └─ agent_tool: apply_patch (1.2秒)
│     └─ run_checks: full (78秒)
│        ├─ rescan (65秒)
│        └─ tests (13秒)
```

### 2. 性能分析

**聚合分析**：
- 哪个工具最慢？
- 哪个规则token消耗最多？
- 成功率随时间的变化趋势

### 3. Prompt管理

**版本控制**：
- 每个prompt的版本历史
- A/B测试不同prompt
- 回滚到之前的版本

### 4. 在线Debug

**实时监控**：
- 正在运行的Agent实时状态
- 看到每一步的输入输出
- 快速定位失败原因

---

## 🚀 接入方案

### 方案1：最小接入（推荐）

**只加环境变量，零代码改动**：

```bash
# .env 或环境变量
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
export LANGCHAIN_API_KEY="your-api-key"
export LANGCHAIN_PROJECT="cleardebt-production"
```

**原理**：LangGraph自动集成LangSmith，只要设置环境变量就会自动上报

**优点**：
✅ 零代码改动
✅ 立即生效
✅ 可以随时关闭（删除环境变量）

**缺点**：
⚠️ 只能看到LangGraph内部的trace
⚠️ 自定义metadata较少

### 方案2：增强接入（推荐用于生产）

**添加自定义metadata**：

```python
# cleardebt/issue_graph.py

def build_graph(checkpointer, **kwargs):
    """添加LangSmith配置"""
    import os
    
    # 配置项目名称
    project = os.getenv("LANGCHAIN_PROJECT", "cleardebt-dev")
    
    builder = StateGraph(IssueState)
    # ... 现有代码 ...
    
    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=kwargs.get("interrupt_before")
    )
    
    return graph


def agent_model(state: IssueState) -> dict:
    """在模型调用中添加metadata"""
    from langsmith import traceable
    
    # 添加自定义标签
    metadata = {
        "rule": state.get("rule"),
        "project": state.get("project"),
        "session_id": state.get("session_id"),
        "tool_count": state.get("agent_tool_count", 0),
    }
    
    # 原有逻辑...
    call = choose_tool(messages, available_tools)
    
    return {
        "agent_call": call,
        # ... 其他字段
    }
```

**添加到scripts/run_issue.py**：

```python
def execute(rule: str, project: str, **kwargs):
    """添加trace metadata"""
    import os
    from langsmith import trace
    
    # 设置trace名称
    trace_name = f"{project}:{rule}"
    
    with trace(
        name=trace_name,
        metadata={
            "rule": rule,
            "project": project,
            "git_branch": kwargs.get("git_branch"),
            "benchmark": bool(kwargs.get("benchmark_read_only")),
        }
    ) as run:
        # 原有执行逻辑
        result = _execute_internal(rule, project, **kwargs)
        
        # 记录结果
        run.metadata.update({
            "level": result.get("level"),
            "fix_method": result.get("fix_method"),
            "rescan_ok": result.get("rescan_ok"),
            "tests_passed": result.get("tests_passed"),
        })
        
        return result
```

### 方案3：完整接入（最大化价值）

**自定义事件记录**：

```python
# cleardebt/agent_tools.py

class AgentTools:
    def execute(self, name: str, args: dict):
        """添加工具调用trace"""
        from langsmith import traceable
        
        @traceable(name=f"tool:{name}")
        def _execute_with_trace():
            try:
                # 原有逻辑
                result, update = self._execute_internal(name, args)
                
                return {"ok": True, "data": result}, update
            except ToolError as error:
                # 记录错误
                return {"ok": False, "error_code": error.code}, {}
        
        return _execute_with_trace()
```

**添加自定义evaluator**：

```python
# bench/langsmith_eval.py

from langsmith import evaluate
from langsmith.schemas import Run, Example

def check_rescan_ok(run: Run, example: Example) -> dict:
    """检查是否通过rescan"""
    outputs = run.outputs or {}
    return {
        "key": "rescan_ok",
        "score": 1 if outputs.get("rescan_ok") else 0
    }

def check_no_new_issues(run: Run, example: Example) -> dict:
    """检查是否引入新问题"""
    outputs = run.outputs or {}
    added = len(outputs.get("rescan_added", []))
    return {
        "key": "no_new_issues",
        "score": 1 if added == 0 else 0
    }

# 运行评估
evaluate(
    lambda inputs: run_agent(inputs["rule"], inputs["project"]),
    data="cleardebt-test-cases",
    evaluators=[check_rescan_ok, check_no_new_issues],
    experiment_prefix="agent-v2"
)
```

---

## 📊 接入后能看到什么？

### 1. Dashboard概览

```
┌─────────────────────────────────────────────────┐
│ ClearDebt Agent - 过去7天                        │
├─────────────────────────────────────────────────┤
│ 总修复数:    342                                 │
│ 成功率:      87.8%                               │
│ 平均耗时:    53.3秒                              │
│ 平均Token:   10,386                              │
│ 平均成本:    $0.0028                             │
├─────────────────────────────────────────────────┤
│ 按规则分类:                                       │
│   javascript:S6582  45次  89% ✅                │
│   javascript:S1854  32次  93% ✅                │
│   javascript:S3358  28次  75% ⚠️                │
├─────────────────────────────────────────────────┤
│ 慢查询 Top 5:                                    │
│   1. rescan (avg 65秒)                          │
│   2. tests (avg 13秒)                           │
│   3. agent_model (avg 2.1秒)                    │
└─────────────────────────────────────────────────┘
```

### 2. 单次运行详情

```
Run: javascript:S6582 @ bench-dayjs
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Timeline:
├─ 0.0s   agent_model (选择工具)
│  ├─ Input: 告警信息 + 可用工具
│  ├─ LLM: deepseek-flash (2.1秒, 1.2K tokens)
│  └─ Output: search_repo("data.items")
│
├─ 2.1s   tool:search_repo (执行搜索)
│  ├─ Input: query="data.items", limit=20
│  ├─ Duration: 0.5秒
│  └─ Output: 3 matches found
│
├─ 2.6s   agent_model (选择工具)
│  ├─ Input: 搜索结果
│  ├─ LLM: deepseek-flash (1.8秒, 0.8K tokens)
│  └─ Output: read_file("src/utils.js", 10, 30)
│
├─ 4.4s   tool:read_file (读取文件)
│  ├─ Input: path="src/utils.js"
│  ├─ Duration: 0.3秒
│  └─ Output: 21行代码 + SHA-256
│
└─ ... (完整调用链)

Metadata:
  rule: javascript:S6582
  project: bench-dayjs
  level: L1
  rescan_ok: true
  tests_passed: true
  total_tokens: 10,234
  total_cost: $0.0028
```

### 3. Prompt查看

```
Prompt: agent-system-v1
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

System:
你是 ClearDebt 修复 Agent。每轮必须调用恰好一个提供的工具。
先取证，再提交最小补丁；补丁后调用 run_checks(full)。
...

Variables:
  - context: {{issue_context}}
  - messages: {{agent_messages}}

Used in:
  - 156 runs (last 7 days)
  - Success rate: 87.8%
  - Avg tokens: 10,386
```

---

## 💰 成本考虑

### LangSmith定价（2024）

```
免费版:
  - 5000 traces/月
  - 保留14天
  - 基础功能

Pro版 ($39/月):
  - 100K traces/月
  - 保留90天
  - 高级分析

Enterprise:
  - 无限traces
  - 自定义保留
  - 私有部署
```

### 你们的预估

```
评测: 120条 × 2模式 = 240 traces
生产: 假设每天10个修复 × 30天 = 300 traces/月

总计: ~540 traces/月

✅ 免费版完全够用！
```

---

## 🎯 推荐接入路径

### 阶段1：快速验证（1小时）

```bash
# 1. 安装langsmith
pip install langsmith

# 2. 添加到requirements.txt
echo "langsmith==0.1.147" >> requirements.txt

# 3. 设置环境变量
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY="your-key"
export LANGCHAIN_PROJECT="cleardebt-dev"

# 4. 运行一个测试
.venv/bin/python scripts/run_issue.py javascript:S1854 bench-dayjs

# 5. 在 https://smith.langchain.com 查看trace
```

### 阶段2：增强metadata（半天）

1. 在`agent_model`添加metadata
2. 在`agent_tool`添加tool trace
3. 在`run_issue.execute`添加顶层trace
4. 测试确认metadata正确

### 阶段3：评测集成（半天）

1. 修改`run_autonomous_compare.py`启用tracing
2. 运行评测，收集traces
3. 在LangSmith创建dataset
4. 设置evaluators

---

## 📝 实施清单

**最小接入（推荐先做）**：
- [ ] 注册LangSmith账号
- [ ] 获取API key
- [ ] 添加环境变量到`.env`
- [ ] 运行测试验证
- [ ] 查看第一个trace

**增强接入**：
- [ ] `pip install langsmith`
- [ ] 添加到`requirements.txt`
- [ ] 在`agent_model`添加metadata
- [ ] 在`agent_tools`添加trace装饰器
- [ ] 在`run_issue.execute`添加顶层trace

**评测集成**：
- [ ] 创建LangSmith dataset
- [ ] 上传120条评测用例
- [ ] 编写evaluators
- [ ] 设置定期评测

---

## 💡 面试加分点

### 如果接入了LangSmith

**面试官**: "怎么监控Agent运行？"

**你**: "我们用LangSmith做全链路trace：
- 每个Agent会话都有完整调用链可视化
- 可以看到每一步的输入输出和耗时
- 按规则聚合分析成功率和token消耗
- 120条评测集每次运行都自动上报到LangSmith

**最有用的是快速定位失败原因：某个规则失败率突然升高，我可以立即看到是哪一步出问题了**"

### 如果还没接入

**面试官**: "怎么监控Agent运行？"

**你**: "目前我们有：
- PostgreSQL checkpoint记录每一步状态
- agent_events表记录工具调用和结果
- 活动页展示工具记录时间线

**下一步计划接入LangSmith，因为它能提供：**
1. 可视化的完整调用链
2. 跨会话的性能分析
3. prompt版本管理
4. 我们的架构已经用LangGraph，接入只需要加环境变量，零代码改动"

**这证明你知道现有方案的局限，并且有改进计划！**

---

## ⚠️ 注意事项

### 隐私和安全

```python
# 敏感信息过滤
import os
os.environ["LANGCHAIN_HIDE_INPUTS"] = "true"  # 隐藏输入
os.environ["LANGCHAIN_HIDE_OUTPUTS"] = "true" # 隐藏输出

# 或者选择性过滤
from langsmith import Client
client = Client()

# 自定义过滤器
def filter_sensitive(data):
    if "token" in data:
        data["token"] = "***"
    return data
```

### 性能影响

```
overhead: ~50-100ms/trace
网络异步发送，不阻塞主流程
失败自动重试，不影响Agent运行
```

### 成本控制

```python
# 只在必要时启用
if os.getenv("ENABLE_LANGSMITH") == "1":
    os.environ["LANGCHAIN_TRACING_V2"] = "true"

# 采样（只记录10%）
import random
if random.random() < 0.1:
    # 启用这次trace
    pass
```

---

## ✅ 总结

**可以接入，而且很简单！**

**最小方案**（1小时）：
```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY="your-key"
# 零代码改动，立即生效
```

**价值**：
- ✅ 完整的trace可视化
- ✅ 跨会话性能分析
- ✅ 快速定位失败原因
- ✅ 免费版够用（5000 traces/月）

**面试加分**：
- 证明你关注可观测性
- 知道现有方案的局限
- 有具体的改进计划

**建议**：先用最小方案验证价值，再逐步增强！🚀
