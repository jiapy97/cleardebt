# 在后台/API触发Agent并上报LangSmith

## 🎯 关键点

只要设置了LangSmith环境变量，**所有Agent运行都会自动上报到LangSmith**，包括：
- 命令行运行
- API调用
- 定时任务
- 手动指派

**不需要额外操作！** 环境变量已经在`.env`文件中配置好了。

---

## 🚀 方式1：通过API触发（推荐）

### 1.1 启动API服务器

```bash
cd /Users/perry/agent项目

# 加载环境变量（包含LangSmith配置）
export $(cat .env | xargs)

# 启动API服务
.venv/bin/uvicorn cleardebt.api:app --host 0.0.0.0 --port 3000
```

### 1.2 通过API运行单个告警

```bash
# 列出test2的所有告警
curl http://localhost:3000/issues?repo=test2

# 手动指派告警
curl -X POST http://localhost:3000/issues/assign \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "test2",
    "issues": [
      {
        "rule": "javascript:S1854",
        "path": "src/status.js",
        "fingerprint": "c51eb821879ca04f338e6aa2d339ed0394bbde4a61c451ab62901278300bc216"
      }
    ]
  }'

# 返回：
# {
#   "started": true,
#   "already_running": false,
#   "repo": "test2",
#   "session_id": 123
# }
```

### 1.3 查看运行状态

```bash
# 查看会话列表
curl http://localhost:3000/sessions

# 查看具体会话
curl http://localhost:3000/api/sessions/123

# 查看活动事件（工具调用记录）
curl http://localhost:3000/api/sessions/123/events
```

### 1.4 批量运行

```bash
# 运行指定项目的所有告警
curl -X POST http://localhost:3000/batch/run?repo=test2

# 运行白名单中的所有项目
curl -X POST http://localhost:3000/batch/run
```

---

## 🌐 方式2：通过控制台界面触发

### 2.1 访问控制台

```bash
# 启动API（如果还没启动）
cd /Users/perry/agent项目
export $(cat .env | xargs)
.venv/bin/uvicorn cleardebt.api:app --host 0.0.0.0 --port 3000
```

访问：http://localhost:3000

### 2.2 手动指派告警

1. 进入"问题"或"Issues"页面
2. 选择项目（如test2）
3. 勾选要修复的告警
4. 点击"指派"或"Assign"按钮

**自动上报**：Agent运行时会自动上报到LangSmith

### 2.3 查看运行记录

在控制台的"会话"或"Sessions"页面：
- 看到正在运行的任务
- 查看历史记录
- 查看每个告警的修复状态

---

## ⏰ 方式3：定时任务自动运行

### 3.1 配置定时任务

在控制台界面：
1. 进入"设置"或"Schedule"页面
2. 启用"定时修复"
3. 配置时间（例如：每天8:00）
4. 保存

或通过API：

```bash
curl -X POST http://localhost:3000/schedule \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "schedule_enabled=true" \
  -d "frequency=daily" \
  -d "hour=8" \
  -d "minute=0" \
  -d "timezone=Asia/Shanghai"
```

### 3.2 定时任务会自动上报

定时任务运行的所有Agent都会自动上报到LangSmith，因为：
1. 定时任务启动时会加载环境变量
2. 环境变量包含LangSmith配置
3. LangGraph自动集成LangSmith

---

## 🔍 方式4：ARQ后台任务（已集成）

你们的系统使用ARQ处理后台任务，这些任务也会自动上报。

### 4.1 ARQ Worker启动

```bash
cd /Users/perry/agent项目

# 加载环境变量（包含LangSmith）
export $(cat .env | xargs)

# 启动ARQ worker
.venv/bin/arq cleardebt.agent_jobs.WorkerSettings
```

### 4.2 提交任务

通过API或控制台提交的任务会进入ARQ队列：

```python
# 代码中已经集成
from cleardebt.agent_jobs import submit

submit("run_assign_session", repo, issues, session_id)
# ↑ 这个任务运行时会自动上报LangSmith
```

---

## 📊 验证LangSmith上报

### 检查1：确认环境变量

```bash
cd /Users/perry/agent项目

# 查看当前环境变量
env | grep LANGCHAIN

# 应该看到：
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=lsv2_pt_d67cafe...
# LANGCHAIN_PROJECT=cleardebt-dev
```

### 检查2：运行一个测试

```bash
# 加载环境变量
export $(cat .env | xargs)

# 运行测试
.venv/bin/python scripts/run_issue.py javascript:S1854 test2

# 访问 LangSmith
# https://smith.langchain.com
# 在 cleardebt-dev 项目中应该能看到新的trace
```

### 检查3：通过API运行

```bash
# 启动API服务
export $(cat .env | xargs)
.venv/bin/uvicorn cleardebt.api:app --port 3000

# 在另一个终端
curl -X POST http://localhost:3000/issues/assign \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "test2",
    "issues": [{
      "rule": "javascript:S1854",
      "path": "src/status.js",
      "fingerprint": "c51eb821879ca04f338e6aa2d339ed0394bbde4a61c451ab62901278300bc216"
    }]
  }'

# 在LangSmith查看trace
```

---

## 🎨 在LangSmith中过滤后台运行的trace

### 按来源过滤

你可以添加metadata来区分不同来源：

```python
# 修改 cleardebt/api.py 中的 assign_issues
@app.post("/issues/assign")
def assign_issues(body: dict = Body(...)) -> dict:
    # 添加metadata
    os.environ["LANGSMITH_EXTRA_METADATA"] = json.dumps({
        "source": "api",
        "endpoint": "/issues/assign"
    })
    
    # 原有逻辑...
    submit("run_assign_session", name, selections, session_id, session_id=session_id)
```

然后在LangSmith中过滤：
```
metadata.source = "api"
metadata.endpoint = "/issues/assign"
```

---

## 💡 实用技巧

### 1. 在不同环境使用不同项目

```bash
# 开发环境
export LANGCHAIN_PROJECT=cleardebt-dev

# API环境
export LANGCHAIN_PROJECT=cleardebt-api

# 定时任务环境
export LANGCHAIN_PROJECT=cleardebt-scheduled
```

### 2. 监控ARQ任务

```bash
# 查看ARQ任务状态
redis-cli -p 6380
> KEYS arq:*
> LLEN arq:queue:default

# 或使用ARQ CLI
.venv/bin/arq cleardebt.agent_jobs.WorkerSettings --check
```

### 3. 查看实时日志

```bash
# API服务日志
.venv/bin/uvicorn cleardebt.api:app --port 3000 --log-level debug

# ARQ worker日志
.venv/bin/arq cleardebt.agent_jobs.WorkerSettings --verbose
```

---

## 📋 完整工作流示例

### 场景：通过API触发Agent修复并查看trace

```bash
# 1. 启动服务（Terminal 1）
cd /Users/perry/agent项目
export $(cat .env | xargs)
.venv/bin/uvicorn cleardebt.api:app --port 3000

# 2. 启动Worker（Terminal 2）
cd /Users/perry/agent项目
export $(cat .env | xargs)
.venv/bin/arq cleardebt.agent_jobs.WorkerSettings

# 3. 提交任务（Terminal 3）
curl -X POST http://localhost:3000/issues/assign \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "test2",
    "issues": [{
      "rule": "javascript:S1854",
      "path": "src/status.js",
      "fingerprint": "c51eb821879ca04f338e6aa2d339ed0394bbde4a61c451ab62901278300bc216"
    }]
  }'

# 4. 查看状态
curl http://localhost:3000/sessions

# 5. 在LangSmith查看trace
# https://smith.langchain.com → cleardebt-dev
```

---

## ✅ 总结

**关键点**：
1. ✅ `.env`文件已配置好LangSmith
2. ✅ 所有运行方式都会自动上报
3. ✅ 不需要修改代码

**运行方式**：
- 命令行：`run_issue.py`
- API：`/issues/assign`
- 批量：`/batch/run`
- 定时任务：自动运行
- ARQ任务：后台队列

**验证方法**：
1. 确保环境变量加载（`export $(cat .env | xargs)`）
2. 运行任何方式的Agent
3. 访问 https://smith.langchain.com
4. 在 `cleardebt-dev` 项目中查看trace

**只要环境变量设置了，一切都会自动上报！** 🎉
