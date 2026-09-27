#!/bin/bash
# 验证LangSmith时间和控制台时间是否匹配

cd /Users/perry/agent项目

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  验证 LangSmith 时间匹配                                            ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# 加载环境变量
export $(cat .env | xargs)

# 记录当前时间（多种格式）
echo "运行前时间:"
echo "  系统时间: $(date)"
echo "  北京时间: $(TZ='Asia/Shanghai' date)"
echo "  UTC时间:  $(TZ='UTC' date)"
echo "  Unix时间戳: $(date +%s)"
echo ""

# 运行一个新的Agent
echo "运行 Agent..."
.venv/bin/python scripts/run_issue.py javascript:S1854 test2

# 记录完成时间
echo ""
echo "运行后时间:"
echo "  系统时间: $(date)"
echo "  北京时间: $(TZ='Asia/Shanghai' date)"
echo "  UTC时间:  $(TZ='UTC' date)"
echo ""

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  完成！                                                             ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "现在："
echo "  1. 访问 https://smith.langchain.com"
echo "  2. 刷新页面"
echo "  3. 查看最新的 LangGraph trace"
echo "  4. 对比上面记录的时间"
echo ""
echo "如果时间相差："
echo "  - 0小时 → 时区一致"
echo "  - 8小时 → LangSmith显示UTC，你的系统是北京时间"
echo "  - 其他 → 可能是不同的运行或浏览器时区问题"
echo ""
