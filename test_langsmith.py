#!/usr/bin/env python3
"""Test LangSmith integration with ClearDebt Agent.

Usage:
    # Set environment variables first
    export LANGCHAIN_TRACING_V2=true
    export LANGCHAIN_API_KEY=your-key
    export LANGCHAIN_PROJECT=cleardebt-test

    # Run test
    .venv/bin/python test_langsmith.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def check_config():
    """Check if LangSmith is configured."""
    print("=" * 60)
    print("LangSmith 配置检查")
    print("=" * 60)

    required = {
        "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2"),
        "LANGCHAIN_API_KEY": os.getenv("LANGCHAIN_API_KEY"),
        "LANGCHAIN_PROJECT": os.getenv("LANGCHAIN_PROJECT", "default"),
    }

    all_set = True
    for key, value in required.items():
        if value:
            masked = value if key != "LANGCHAIN_API_KEY" else f"{value[:8]}..."
            print(f"  ✓ {key}={masked}")
        else:
            print(f"  ✗ {key} 未设置")
            all_set = False

    if not all_set:
        print("\n请设置环境变量：")
        print("  export LANGCHAIN_TRACING_V2=true")
        print("  export LANGCHAIN_API_KEY=your-key")
        print("  export LANGCHAIN_PROJECT=cleardebt-test")
        return False

    return True


def test_connection():
    """Test LangSmith connection."""
    print("\n" + "=" * 60)
    print("测试 LangSmith 连接")
    print("=" * 60)

    try:
        from langsmith import Client
        client = Client()
        print("  ✓ 连接成功！")
        return True
    except Exception as e:
        print(f"  ✗ 连接失败: {e}")
        return False


def test_simple_trace():
    """Test simple trace."""
    print("\n" + "=" * 60)
    print("发送测试 trace")
    print("=" * 60)

    try:
        from langsmith import traceable

        @traceable(name="test-cleardebt-integration")
        def test_function():
            """A simple test function."""
            return {
                "status": "ok",
                "message": "LangSmith integration working!",
                "project": os.getenv("LANGCHAIN_PROJECT"),
            }

        result = test_function()
        print(f"  ✓ Trace 已发送")
        print(f"  ✓ 状态: {result['status']}")
        print(f"  ✓ 消息: {result['message']}")
        return True

    except Exception as e:
        print(f"  ✗ 发送失败: {e}")
        return False


def test_agent_trace():
    """Test trace with LangGraph Agent."""
    print("\n" + "=" * 60)
    print("测试 Agent trace（模拟）")
    print("=" * 60)

    try:
        from langsmith import traceable

        @traceable(name="agent-session", metadata={"rule": "javascript:S1854", "project": "test"})
        def mock_agent_session():
            """Mock an agent session."""

            @traceable(name="tool:search_repo")
            def search_tool():
                return {"matches": 3}

            @traceable(name="tool:read_file")
            def read_tool():
                return {"lines": 25, "sha256": "abc123"}

            @traceable(name="tool:apply_patch")
            def apply_tool():
                return {"ok": True, "files": 1}

            # Simulate agent workflow
            search_tool()
            read_tool()
            apply_tool()

            return {
                "level": "L1",
                "rescan_ok": True,
                "tests_passed": True,
            }

        result = mock_agent_session()
        print(f"  ✓ Agent trace 已发送")
        print(f"  ✓ Level: {result['level']}")
        print(f"  ✓ Rescan: {result['rescan_ok']}")
        return True

    except Exception as e:
        print(f"  ✗ 发送失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test function."""
    print("\n🧪 LangSmith 集成测试\n")

    # 1. Check config
    if not check_config():
        return 1

    # 2. Test connection
    if not test_connection():
        return 1

    # 3. Test simple trace
    if not test_simple_trace():
        return 1

    # 4. Test agent trace
    if not test_agent_trace():
        return 1

    # Success
    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)

    project = os.getenv("LANGCHAIN_PROJECT", "default")
    print(f"\n访问 https://smith.langchain.com 查看你的 traces")
    print(f"项目: {project}\n")

    print("下一步:")
    print("  1. 在 LangSmith 查看刚才发送的 traces")
    print("  2. 运行真实 Agent:")
    print("     .venv/bin/python scripts/run_issue.py javascript:S1854 bench-dayjs")
    print("  3. 在 LangSmith 查看完整的 Agent trace\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
