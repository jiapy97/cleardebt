#!/bin/bash
# 测试通过API触发Agent并在LangSmith查看trace

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  测试 API 触发 Agent → LangSmith                                    ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

API_URL="http://localhost:3000"

# 检查API是否运行
echo "1. 检查API服务..."
if curl -s "$API_URL" > /dev/null 2>&1; then
    echo "  ✓ API服务运行中"
else
    echo "  ✗ API服务未运行"
    echo ""
    echo "请先启动API服务:"
    echo "  ./start_api.sh"
    echo ""
    echo "或手动启动:"
    echo "  cd /Users/perry/agent项目"
    echo "  export \$(cat .env | xargs)"
    echo "  .venv/bin/uvicorn cleardebt.api:app --port 3000"
    exit 1
fi

echo ""
echo "2. 列出test2的告警..."
curl -s "$API_URL/issues?repo=test2" | head -20
echo ""

echo ""
echo "3. 提交修复任务..."
response=$(curl -s -X POST "$API_URL/issues/assign" \
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
  }')

echo "$response" | python3 -m json.tool

session_id=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('session_id', ''))")

if [ -z "$session_id" ]; then
    echo ""
    echo "  ✗ 任务提交失败"
    exit 1
fi

echo ""
echo "  ✓ 任务已提交"
echo "  Session ID: $session_id"

echo ""
echo "4. 查看任务状态..."
sleep 2
curl -s "$API_URL/api/sessions/$session_id" | python3 -m json.tool

echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ 测试完成                                                         ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "现在访问 LangSmith 查看 trace:"
echo "  https://smith.langchain.com"
echo ""
echo "项目: cleardebt-dev"
echo "Session ID: $session_id"
echo ""
echo "你应该能看到完整的Agent trace，包括:"
echo "  - triage → fix → rescan → test → decide"
echo "  - 每一步的输入输出"
echo "  - 耗时和token消耗"
echo ""
