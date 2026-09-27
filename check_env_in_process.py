#!/usr/bin/env python3
"""检查API进程是否真的加载了环境变量"""

import os
import sys

print("当前Python进程的环境变量:")
print(f"LANGCHAIN_TRACING_V2 = {os.getenv('LANGCHAIN_TRACING_V2')}")
print(f"LANGCHAIN_API_KEY = {os.getenv('LANGCHAIN_API_KEY', '')[:12]}...")
print(f"LANGCHAIN_PROJECT = {os.getenv('LANGCHAIN_PROJECT')}")

if os.getenv('LANGCHAIN_TRACING_V2') != 'true':
    print("\n❌ 环境变量未设置！")
    sys.exit(1)
else:
    print("\n✅ 环境变量已设置")
