#!/bin/bash
# 测试 LangSmith 与真实 Agent 集成

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  测试 LangSmith 与真实 Agent 集成                                    ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# 1. 加载环境变量
echo "1. 加载 LangSmith 环境变量..."
cd /Users/perry/agent项目
export $(cat .env | xargs)
echo "   ✓ 已加载"
echo ""

# 2. 运行真实 Agent
echo "2. 运行真实 Agent（test2 项目有 token 可以实际修复）..."
echo "   执行: .venv/bin/python scripts/run_issue.py javascript:S1854 test2"
echo ""

.venv/bin/python scripts/run_issue.py javascript:S1854 test2

# 3. 提示
echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  🎉 完成！                                                           ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "现在访问 https://smith.langchain.com 查看完整的 Agent trace！"
echo ""
echo "你会看到："
echo "  ├─ agent_model (选择工具)"
echo "  │  └─ LLM Call: deepseek-flash"
echo "  ├─ tool:search_repo / tool:read_file"
echo "  ├─ agent_model"
echo "  │  └─ LLM Call: deepseek-flash"
echo "  └─ tool:apply_patch"
echo "     └─ run_checks: full"
echo ""
