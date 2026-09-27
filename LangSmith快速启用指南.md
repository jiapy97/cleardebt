# LangSmith 快速启用指南

## ✅ 已完成的准备工作

1. ✅ langsmith已安装（v0.14.0）
2. ✅ 已添加到requirements.txt
3. ✅ 创建了.env.example模板
4. ✅ 创建了测试脚本test_langsmith.py

## 🚀 3步启用LangSmith

### 步骤1：获取API Key（2分钟）

1. 访问 https://smith.langchain.com
2. 注册/登录账号
3. 进入 Settings → API Keys
4. 创建新的API Key
5. 复制API Key（只显示一次！）

### 步骤2：设置环境变量（1分钟）

**方式A：临时设置（推荐先测试）**

```bash
cd /Users/perry/agent项目

export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=lsv2_pt_xxxxxxxxxxxxx  # 替换成你的key
export LANGCHAIN_PROJECT=cleardebt-dev
```

**方式B：创建.env文件（长期使用）**

```bash
# 复制模板
cp .env.example .env

# 编辑.env文件，填入你的API key
vim .env
```

编辑内容：
```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_xxxxxxxxxxxxx  # 替换成你的实际key
LANGCHAIN_PROJECT=cleardebt-dev
```

**然后加载环境变量**：
```bash
source .env
# 或
export $(cat .env | xargs)
```

### 步骤3：测试连接（2分钟）

```bash
# 运行测试脚本
.venv/bin/python test_langsmith.py
```

**预期输出**：
```
🧪 LangSmith 集成测试

============================================================
LangSmith 配置检查
============================================================
  ✓ LANGCHAIN_TRACING_V2=true
  ✓ LANGCHAIN_API_KEY=lsv2_pt_...
  ✓ LANGCHAIN_PROJECT=cleardebt-dev

============================================================
测试 LangSmith 连接
============================================================
  ✓ 连接成功！

============================================================
发送测试 trace
============================================================
  ✓ Trace 已发送
  ✓ 状态: ok
  ✓ 消息: LangSmith integration working!

============================================================
测试 Agent trace（模拟）
============================================================
  ✓ Agent trace 已发送
  ✓ Level: L1
  ✓ Rescan: True

============================================================
✅ 所有测试通过！
============================================================

访问 https://smith.langchain.com 查看你的 traces
项目: cleardebt-dev
```

---

## 🎯 查看第一个Trace

1. 访问 https://smith.langchain.com
2. 选择项目 `cleardebt-dev`
3. 在 Traces 页面看到：
   - `test-cleardebt-integration` - 简单测试
   - `agent-session` - 模拟Agent会话
     - `tool:search_repo`
     - `tool:read_file`
     - `tool:apply_patch`

---

## 🚀 测试真实Agent

**现在环境变量已设置，直接运行Agent即可自动上报trace**：

```bash
# 运行一个真实的修复
.venv/bin/python scripts/run_issue.py javascript:S1854 bench-dayjs
```

**在LangSmith查看**：
- 完整的Agent会话trace
- 每个工具调用的输入输出
- LLM调用的token消耗
- 每一步的耗时

---

## 🔧 高级配置（可选）

### 隐藏敏感数据

```bash
export LANGCHAIN_HIDE_INPUTS=true   # 隐藏输入
export LANGCHAIN_HIDE_OUTPUTS=true  # 隐藏输出
```

### 采样（只trace部分请求）

```bash
export LANGCHAIN_TRACING_SAMPLING_RATE=0.1  # 只trace 10%
```

### 不同环境使用不同项目

```bash
# 开发环境
export LANGCHAIN_PROJECT=cleardebt-dev

# 评测环境
export LANGCHAIN_PROJECT=cleardebt-benchmark

# 生产环境
export LANGCHAIN_PROJECT=cleardebt-production
```

---

## 📊 运行评测并上报

```bash
# 设置环境变量
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=your-key
export LANGCHAIN_PROJECT=cleardebt-benchmark

# 运行评测（会自动上报所有trace）
.venv/bin/python bench/run_autonomous_compare.py --per-project 10

# 在LangSmith查看
# 按规则聚合分析成功率、token消耗等
```

---

## 🎓 在LangSmith中分析数据

### 1. 按规则过滤

在Filters中添加：
```
metadata.rule = "javascript:S1854"
```

### 2. 按成功率排序

在Columns中添加：
- `metadata.level` 
- `metadata.rescan_ok`
- `metadata.tests_passed`

### 3. 查看慢查询

按Duration排序，找到最慢的trace

### 4. 分析Token消耗

查看每个trace的token使用情况，按规则聚合

---

## ⚠️ 注意事项

### 1. .env文件安全

```bash
# 确保.env文件不会被提交到git
echo ".env" >> .gitignore
```

### 2. API Key保护

- ❌ 不要把API key提交到代码库
- ❌ 不要在日志中打印API key
- ✅ 使用环境变量
- ✅ 使用.env文件（并加入.gitignore）

### 3. 性能影响

- Overhead: ~50-100ms/trace
- 异步发送，不阻塞Agent运行
- 失败自动重试，不影响Agent

### 4. 成本控制

免费版：5000 traces/月
- 评测：240 traces
- 日常开发：~300 traces/月
- 总计：~540 traces/月

✅ 完全在免费额度内

---

## 🆘 故障排查

### 问题1：连接失败

```
✗ 连接失败: Unauthorized
```

**解决**：检查API key是否正确

```bash
echo $LANGCHAIN_API_KEY  # 确认key已设置
```

### 问题2：看不到trace

**可能原因**：
1. 环境变量未设置
2. 项目名称不匹配
3. 网络问题

**排查**：
```bash
# 检查环境变量
env | grep LANGCHAIN

# 查看日志
# LangSmith错误会打印到stderr
```

### 问题3：trace不完整

**原因**：程序崩溃导致trace未上报

**解决**：trace在程序正常退出时才会完整上报

---

## ✅ 验收清单

- [ ] 获取了LangSmith API key
- [ ] 设置了环境变量（或创建了.env文件）
- [ ] 运行test_langsmith.py全部通过
- [ ] 在LangSmith看到了测试trace
- [ ] 运行了真实Agent并看到trace
- [ ] 在LangSmith查看了完整的调用链
- [ ] .env文件已加入.gitignore

---

## 🎉 完成！

现在你已经完成了LangSmith接入：

✅ **零代码改动**  
✅ **立即生效**  
✅ **完整trace可视化**  
✅ **性能分析**  
✅ **免费额度够用**  

**下一步**：
1. 在LangSmith探索各种功能
2. 运行评测并分析结果
3. 使用Playground调试prompt
4. 设置evaluators做自动评估

---

## 📚 更多资源

- 官方文档: https://docs.smith.langchain.com
- 完整接入方案: `LangSmith接入方案.md`
- 测试脚本: `test_langsmith.py`
- 环境变量模板: `.env.example`
