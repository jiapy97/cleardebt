# 为什么LangSmith没有显示完整的LangGraph trace？

## 🔍 你看到的问题

### 控制台（agent_events表）
显示了完整的Agent工具调用：
- get_issue_context
- read_file
- apply_patch
- run_checks
- 处理结论

### LangSmith（traces页面）
只显示3个独立的trace：
- LangGraph (31.00s)
- agent-session (0.00s)
- test-cleardebt-integration (0.02s)

**问题**：看不到LangGraph内部的状态机步骤！

---

## 💡 原因分析

### 你需要点击LangGraph trace展开！

在LangSmith界面：

1. **点击"LangGraph"那一行**
2. 左侧会展开显示子步骤
3. 你会看到完整的状态机

类似这样：
```
LangGraph (31.00s)
├─ triage (0.00s)
├─ route_after_triage (0.00s)
├─ fix (0.00s)
├─ route_after_fix (0.00s)
├─ anti_cheat (0.00s)
├─ route_after_anti_cheat (0.00s)
├─ rescan (30.96s)      ← 点击这个可以看rescan的细节
├─ route_after_rescan (0.00s)
├─ test (0.00s)
├─ route_after_test (0.00s)
└─ decide (0.00s)
```

---

## 🎯 操作步骤

### 步骤1：点击LangGraph行

在Traces页面，点击"LangGraph (31.00s)"这一行

### 步骤2：查看左侧树形结构

点击后，左侧会出现树形结构，显示所有节点

### 步骤3：点击任意节点

点击左侧的任意节点（如"rescan"），右侧会显示：
- **Input** tab: 这一步的输入
- **Output** tab: 这一步的输出
- **Metadata** tab: 元数据

### 步骤4：查看工具调用（如果是Agent模式）

如果这个case走的是Agent模式（不是mechanical），你会看到：
```
agent_model
├─ Input: 问题上下文 + 可用工具
├─ LLM Call: deepseek-flash
│  ├─ Prompt tokens: 1234
│  ├─ Completion tokens: 56
│  └─ Duration: 2.1s
└─ Output: {"tool": "search_repo", "args": {...}}
```

---

## ⚠️ 为什么只显示3个trace？

### 1. LangGraph (31.00s)
这是**主trace**，包含完整的状态机流程
- 点击它就能看到所有子步骤

### 2. agent-session (0.00s)
这是**测试trace**，我们运行test_langsmith.py时发送的模拟Agent会话

### 3. test-cleardebt-integration (0.02s)
这是**测试trace**，我们运行test_langsmith.py时发送的简单测试

---

## 🔧 如果还是看不到子步骤

### 可能原因1：界面没有展开

**解决**：
- 点击左侧的箭头/三角形图标
- 或者双击trace行

### 可能原因2：trace没有正确嵌套

**检查**：
```bash
cd /Users/perry/agent项目
export $(cat .env | xargs)

# 运行一个新的trace
.venv/bin/python scripts/run_issue.py javascript:S1854 test2

# 然后在LangSmith刷新页面
# 应该看到新的LangGraph trace
```

### 可能原因3：LangGraph版本问题

**检查版本**：
```bash
.venv/bin/pip show langgraph
```

应该是 >= 0.0.50（支持自动trace）

**升级**：
```bash
.venv/bin/pip install --upgrade langgraph
```

---

## 📊 正确的LangSmith界面应该是这样

### Traces列表（顶层）
```
Name              Input               Output          Start Time      Latency
LangGraph         24b4b787199d...     import {...     9/27/2026...    31.00s
agent-session                         L1              9/27/2026...    0.00s
test-cleardebt... 
```

### 点击LangGraph后（左侧树形）
```
▼ LangGraph
  ├─ triage
  ├─ route_after_triage
  ├─ fix
  ├─ route_after_fix
  ├─ anti_cheat
  ├─ route_after_anti_cheat
  ├─ rescan          ← 点击这个
  ├─ route_after_rescan
  ├─ test
  ├─ route_after_test
  └─ decide
```

### 点击rescan后（右侧详情）
```
Tabs: Feedback | Input | Output | Attributes

Input:
{
  "project": "test4",
  "rule": "javascript:S6582",
  "path": "lib/auth.js",
  ...
}

Output:
{
  "rescan_ok": true,
  "rescan_removed": [...],
  "rescan_added": [],
  "history": ["rescan"]
}
```

---

## 🎓 你的控制台vs LangSmith

### 控制台的agent_events表
- 记录**Agent模式**的工具调用
- 只有走Agent模式才有这些记录
- 存储在你们自己的数据库

### LangSmith的traces
- 记录**所有LangGraph运行**
- 包括mechanical和agent模式
- 显示完整的状态机流程

### 你的case (test4, javascript:S6582)
```
控制台显示:
  模型 → 选择工具: get_issue_context, read_file
  get_issue_context → 完成
  read_file → 完成
  模型 → 选择工具: apply_patch
  apply_patch → 完成
  模型 → 选择工具: run_checks
  run_checks → full: 通过

这说明: 走的是Agent模式（有多轮LLM调用）

LangSmith应该显示:
  LangGraph
  ├─ triage → 决定走agent模式
  ├─ agent_model → 选择get_issue_context
  ├─ agent_tool → 执行get_issue_context
  ├─ agent_model → 选择read_file
  ├─ agent_tool → 执行read_file
  ├─ agent_model → 选择apply_patch
  ├─ agent_tool → 执行apply_patch
  ├─ agent_model → 选择run_checks
  ├─ agent_tool → 执行run_checks
  ├─ anti_cheat → 检查
  ├─ rescan → 重扫
  ├─ test → 测试
  └─ decide → L1
```

---

## ✅ 下一步

1. **在LangSmith点击"LangGraph"那一行**
2. **查看左侧是否出现树形结构**
3. **如果没有，刷新页面再试**
4. **如果还是没有，运行新的trace并截图**

你应该能看到完整的状态机流程！🎯
