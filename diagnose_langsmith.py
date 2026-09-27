#!/usr/bin/env python3
"""诊断为什么LangSmith没有完整的trace"""

import os
import sys

print("=" * 70)
print("LangSmith 配置诊断")
print("=" * 70)

# 1. 检查环境变量
print("\n1. 环境变量:")
env_vars = {
    "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2"),
    "LANGCHAIN_API_KEY": os.getenv("LANGCHAIN_API_KEY"),
    "LANGCHAIN_PROJECT": os.getenv("LANGCHAIN_PROJECT"),
    "LANGCHAIN_ENDPOINT": os.getenv("LANGCHAIN_ENDPOINT"),
}

all_set = True
for key, value in env_vars.items():
    if value:
        masked = value if key != "LANGCHAIN_API_KEY" else f"{value[:12]}..."
        print(f"  ✓ {key}={masked}")
    else:
        print(f"  ✗ {key} 未设置")
        all_set = False

if not all_set:
    print("\n  ⚠️  环境变量未完全设置")
    print("  运行: export $(cat .env | xargs)")
    sys.exit(1)

# 2. 测试LangSmith连接
print("\n2. LangSmith 连接:")
try:
    from langsmith import Client
    client = Client()
    print("  ✓ 连接成功")
except Exception as e:
    print(f"  ✗ 连接失败: {e}")
    sys.exit(1)

# 3. 检查LangGraph版本
print("\n3. LangGraph 版本:")
try:
    import langgraph
    print(f"  ✓ langgraph=={langgraph.__version__}")
except Exception as e:
    print(f"  ✗ 无法导入: {e}")

# 4. 测试简单trace
print("\n4. 测试发送trace...")
try:
    from langsmith import traceable
    
    @traceable(name="test-diagnose")
    def test_func():
        return {"status": "ok", "message": "诊断测试"}
    
    result = test_func()
    print(f"  ✓ Trace已发送: {result['message']}")
except Exception as e:
    print(f"  ✗ 发送失败: {e}")

# 5. 检查LangGraph的自动集成
print("\n5. LangGraph自动集成:")
print("  LangGraph应该自动集成LangSmith")
print("  如果环境变量设置了，所有LangGraph运行都应该上报")

# 6. 检查可能的问题
print("\n6. 可能的问题:")
print("  问题1: 环境变量在Agent运行时没有加载")
print("    解决: 确保启动服务前 export $(cat .env | xargs)")
print("")
print("  问题2: LangGraph版本太旧，不支持自动集成")
print("    解决: pip install --upgrade langgraph")
print("")
print("  问题3: 运行在子进程中，环境变量没有传递")
print("    解决: 在子进程启动时也设置环境变量")

print("\n" + "=" * 70)
print("诊断完成")
print("=" * 70)
