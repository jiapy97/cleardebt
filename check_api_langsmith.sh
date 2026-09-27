#!/bin/bash
# 检查后台/API运行是否上报到LangSmith

cd /Users/perry/agent项目

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  检查后台运行是否上报到 LangSmith                                   ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

echo "1. 检查环境变量是否设置..."
if [ -z "$LANGCHAIN_TRACING_V2" ]; then
    echo "  ✗ LANGCHAIN_TRACING_V2 未设置"
    echo ""
    echo "  原因: 后台服务启动时没有加载环境变量！"
    echo ""
    echo "  解决方法:"
    echo "    1. 停止当前的API服务"
    echo "    2. 重新启动，确保加载环境变量:"
    echo ""
    echo "       cd /Users/perry/agent项目"
    echo "       export \$(cat .env | xargs)"
    echo "       .venv/bin/uvicorn cleardebt.api:app --port 3000"
    echo ""
    exit 1
else
    echo "  ✓ LANGCHAIN_TRACING_V2=$LANGCHAIN_TRACING_V2"
    echo "  ✓ LANGCHAIN_PROJECT=$LANGCHAIN_PROJECT"
fi

echo ""
echo "2. 检查API进程的环境变量..."

# 查找uvicorn进程
pid=$(pgrep -f "uvicorn cleardebt.api:app" | head -1)

if [ -z "$pid" ]; then
    echo "  ⚠️  API服务未运行"
    echo ""
    echo "  启动API服务:"
    echo "    export \$(cat .env | xargs)"
    echo "    .venv/bin/uvicorn cleardebt.api:app --port 3000"
    exit 0
fi

echo "  ✓ API进程: $pid"

# 检查进程的环境变量（macOS）
if [ -f "/proc/$pid/environ" ]; then
    # Linux
    if grep -q "LANGCHAIN_TRACING_V2=true" /proc/$pid/environ 2>/dev/null; then
        echo "  ✓ 进程已加载LangSmith环境变量"
    else
        echo "  ✗ 进程未加载LangSmith环境变量"
        echo ""
        echo "  原因: API启动前没有 export 环境变量"
        echo "  解决: 重启API服务，先执行 export \$(cat .env | xargs)"
    fi
else
    # macOS - 无法直接读取进程环境变量
    echo "  ⚠️  macOS无法直接检查进程环境变量"
    echo "  请确认启动API前执行了: export \$(cat .env | xargs)"
fi

echo ""
echo "3. 建议的启动流程..."
cat << 'SCRIPT'

  # Terminal 1: 启动API
  cd /Users/perry/agent项目
  export $(cat .env | xargs)  # ← 关键：加载环境变量
  .venv/bin/uvicorn cleardebt.api:app --port 3000

  # Terminal 2: 启动Worker（如果需要）
  cd /Users/perry/agent项目
  export $(cat .env | xargs)  # ← 关键：加载环境变量
  .venv/bin/arq cleardebt.agent_jobs.WorkerSettings

SCRIPT

echo ""
echo "4. 测试API调用..."
echo "  运行后查看LangSmith是否有新trace:"
echo ""
echo "  curl -X POST http://localhost:3000/issues/assign \\"
echo "    -H \"Content-Type: application/json\" \\"
echo "    -d '{"
echo "      \"repo\": \"test4\","
echo "      \"issues\": [{"
echo "        \"rule\": \"javascript:S6582\","
echo "        \"path\": \"lib/auth.js\","
echo "        \"fingerprint\": \"your-fingerprint\""
echo "      }]"
echo "    }'"
echo ""
echo "  然后立即去 https://smith.langchain.com 查看"
echo ""

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  关键问题：API启动前是否执行了 export \$(cat .env | xargs) ？         ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
