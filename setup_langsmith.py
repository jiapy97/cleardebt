#!/usr/bin/env python3
"""Quick setup script for LangSmith integration.

Usage:
    python setup_langsmith.py --api-key YOUR_KEY
"""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Setup LangSmith for ClearDebt")
    parser.add_argument("--api-key", required=True, help="LangSmith API key")
    parser.add_argument("--project", default="cleardebt-dev", help="Project name")
    args = parser.parse_args()

    print("=" * 60)
    print("LangSmith 快速接入")
    print("=" * 60)

    # 1. 检查是否已安装langsmith
    print("\n1. 检查依赖...")
    try:
        import langsmith
        print("   ✓ langsmith 已安装")
    except ImportError:
        print("   ✗ langsmith 未安装")
        print("\n   运行: pip install langsmith")
        return 1

    # 2. 更新requirements.txt
    print("\n2. 更新 requirements.txt...")
    req_file = Path(__file__).parent / "requirements.txt"
    requirements = req_file.read_text()

    if "langsmith" in requirements:
        print("   ✓ requirements.txt 已包含 langsmith")
    else:
        with open(req_file, "a") as f:
            f.write("langsmith==0.1.147\n")
        print("   ✓ 已添加 langsmith==0.1.147")

    # 3. 创建.env文件
    print("\n3. 配置环境变量...")
    env_file = Path(__file__).parent / ".env"

    env_content = f"""# LangSmith Configuration
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY={args.api_key}
LANGCHAIN_PROJECT={args.project}

# Optional: Hide sensitive data
# LANGCHAIN_HIDE_INPUTS=true
# LANGCHAIN_HIDE_OUTPUTS=true
"""

    if env_file.exists():
        print("   ⚠️  .env 文件已存在")
        response = input("   覆盖? (y/N): ")
        if response.lower() != 'y':
            print("   跳过 .env 文件创建")
            print("\n   请手动添加以下内容到 .env:")
            print(env_content)
            return 0

    env_file.write_text(env_content)
    print(f"   ✓ 已创建 .env 文件")

    # 4. 测试连接
    print("\n4. 测试 LangSmith 连接...")
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = args.api_key
    os.environ["LANGCHAIN_PROJECT"] = args.project

    try:
        from langsmith import Client
        client = Client()
        print("   ✓ 连接成功！")

        # 创建测试trace
        from langsmith import traceable

        @traceable(name="test-trace")
        def test_function():
            return {"status": "ok", "message": "LangSmith setup complete!"}

        result = test_function()
        print(f"   ✓ 测试trace已发送: {result['message']}")

    except Exception as e:
        print(f"   ✗ 连接失败: {e}")
        return 1

    # 5. 完成
    print("\n" + "=" * 60)
    print("✅ LangSmith 接入完成!")
    print("=" * 60)
    print(f"\n访问 https://smith.langchain.com/o/{args.project}")
    print("查看你的第一个trace!\n")

    print("下一步:")
    print("  1. 运行测试: .venv/bin/python scripts/run_issue.py javascript:S1854 bench-dayjs")
    print("  2. 在 LangSmith 查看 trace")
    print("  3. 查看 LangSmith接入方案.md 了解更多功能\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
