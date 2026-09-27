#!/bin/bash
# 启动API服务器（已集成LangSmith）

cd /Users/perry/agent项目

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  启动 ClearDebt API 服务器（已集成 LangSmith）                      ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# 加载环境变量（包含LangSmith配置）
echo "1. 加载环境变量..."
export $(cat .env | xargs 2>/dev/null)

if [ -z "$LANGCHAIN_API_KEY" ]; then
    echo "  ⚠️  LANGCHAIN_API_KEY 未设置"
    echo "  LangSmith将不会上报trace"
else
    echo "  ✓ LANGCHAIN_TRACING_V2=$LANGCHAIN_TRACING_V2"
    echo "  ✓ LANGCHAIN_API_KEY=${LANGCHAIN_API_KEY:0:12}..."
    echo "  ✓ LANGCHAIN_PROJECT=$LANGCHAIN_PROJECT"
fi

echo ""
echo "2. 启动API服务器..."
echo "  访问: http://localhost:3000"
echo "  Swagger: http://localhost:3000/docs"
echo ""

# 启动uvicorn
.venv/bin/uvicorn cleardebt.api:app --host 0.0.0.0 --port 3000 --reload
