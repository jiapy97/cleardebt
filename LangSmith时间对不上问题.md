# LangSmith 时间对不上的问题

## 🕐 你发现的问题

### 控制台显示
```
时间（北京）：2026-09-27 13:17
项目：test4
来源：手动指派
```

### LangSmith显示
```
时间：9/27/2026, 12:05:53 PM
Input：24b4b787199d3cd8197f...
Output：import { STATUS_OK } from...
```

**时间相差1小时12分钟！**

---

## 🔍 分析

### 可能性1：时区差异

**控制台**：
- 显示的是"北京时间"
- UTC+8

**LangSmith**：
- 可能显示的是你浏览器的本地时间
- 或者UTC时间
- 或者其他时区

**计算**：
```
北京时间 13:17 (UTC+8)
= UTC 05:17

如果LangSmith显示 12:05 PM:
- 如果是UTC → 不对（应该是05:17）
- 如果是UTC-7 → 对不上
- 如果是其他时区 → 需要确认
```

### 可能性2：不是同一个trace

**判断方法**：查看详细信息

#### 步骤1：在LangSmith查看Input tab

点击LangSmith的"Input"标签，查找：
```json
{
  "project": "test4" 或 "test2"?,
  "rule": "javascript:S6582" 或 "javascript:S1854"?,
  "path": "lib/auth.js"?,
  "fingerprint": "具体值"
}
```

#### 步骤2：对比控制台

控制台显示：
```
项目：test4
来源：手动指派
时间：2026-09-27 13:17
```

#### 步骤3：对比fingerprint

如果fingerprint不同 = 不是同一个trace

---

## 💡 如何确认是否匹配

### 方法1：在LangSmith搜索

在LangSmith的Filter框输入：
```
metadata.project = "test4"
```

或者：
```
start time: 2026-09-27 13:00 - 13:30 (北京时间)
```

### 方法2：查看所有trace

在LangSmith Traces页面：
1. 按时间排序（最新的在前）
2. 找到与控制台时间接近的trace
3. 点击查看详情
4. 对比project、rule、fingerprint

### 方法3：运行一个新的trace

```bash
cd /Users/perry/agent项目
export $(cat .env | xargs)

# 记录当前时间
date

# 运行Agent
.venv/bin/python scripts/run_issue.py javascript:S1854 test2

# 再记录时间
date

# 然后立即去LangSmith查看
# 应该能看到刚才的trace
```

---

## 🎯 LangSmith时区设置

### 检查浏览器时区

LangSmith通常使用浏览器的本地时区。

**在浏览器Console运行**：
```javascript
console.log(new Date().toString())
console.log(Intl.DateTimeFormat().resolvedOptions().timeZone)
```

这会显示你浏览器的时区设置。

### 常见情况

如果你的浏览器设置在：
- **中国** → 应该显示北京时间（UTC+8）
- **美国西海岸** → 显示PST/PDT（UTC-7/-8）
- **UTC** → 显示UTC时间

---

## 📊 如何验证是否上报成功

### 验证1：trace数量增加

**操作前**：
- 记录LangSmith的trace总数

**运行Agent**：
```bash
.venv/bin/python scripts/run_issue.py javascript:S1854 test2
```

**操作后**：
- 刷新LangSmith页面
- trace总数应该+1

### 验证2：metadata匹配

在新trace的详情页查看：
```json
{
  "metadata": {
    "project": "test2",
    "rule": "javascript:S1854",
    "session_id": 具体数字,
    ...
  }
}
```

与控制台的信息对比。

### 验证3：实时测试

```bash
# Terminal 1: 启动API
cd /Users/perry/agent项目
export $(cat .env | xargs)
.venv/bin/uvicorn cleardebt.api:app --port 3000

# Terminal 2: 调用API
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

# 记录时间：2026-09-27 XX:XX
# 立即去LangSmith查看
# 应该能看到刚才的trace，时间应该接近
```

---

## ⚠️ 可能的问题

### 问题1：时间戳精度

**控制台**：
- 只显示到分钟：13:17
- 可能实际是 13:17:45

**LangSmith**：
- 显示到秒：12:05:53
- 精确时间

如果是同一个trace，应该：
```
控制台：13:17:XX
LangSmith：13:17:XX (转换成北京时间后)
```

### 问题2：不同的运行

**可能情况**：
- 控制台显示的是 13:17 运行的 test4
- LangSmith显示的是 12:05 运行的 test2
- 它们是两次不同的运行

**验证方法**：
查看LangSmith Output中的 `project` 字段：
- 如果是 `test4` → 是同一个，只是时区问题
- 如果是 `test2` → 是不同的运行

---

## ✅ 推荐操作

### 1. 确认时区

在LangSmith界面：
1. 点击右上角的设置/用户图标
2. 查看是否有时区设置
3. 设置为"Asia/Shanghai"或"UTC+8"

### 2. 运行实时测试

```bash
cd /Users/perry/agent项目
export $(cat .env | xargs)

# 运行一个新的trace
echo "运行时间: $(date)"
.venv/bin/python scripts/run_issue.py javascript:S1854 test3
echo "完成时间: $(date)"

# 立即去LangSmith查看
# 记录LangSmith显示的时间
# 计算时差
```

### 3. 添加自定义metadata

修改代码，添加时间戳metadata：

```python
# 在运行前设置
import os
import json
from datetime import datetime

os.environ["LANGSMITH_EXTRA_METADATA"] = json.dumps({
    "local_time": datetime.now().isoformat(),
    "timezone": "Asia/Shanghai"
})
```

然后在LangSmith的metadata中就能看到准确的本地时间。

---

## 📝 总结

**时间对不上的可能原因**：

1. ✅ **最可能**：时区差异
   - 控制台显示北京时间
   - LangSmith显示其他时区

2. 可能：不是同一个trace
   - 控制台：test4 @ 13:17
   - LangSmith：test2 @ 12:05

3. 可能：LangSmith显示延迟
   - trace上报有延迟
   - 显示的时间是上报时间，不是运行时间

**验证方法**：

运行一个新的trace，同时记录两边的时间，计算时差。

如果时差固定（如1小时或8小时），说明是时区问题。

如果找不到对应的trace，说明上报有问题或是不同的运行。
