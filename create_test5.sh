#!/bin/bash
# 自动创建test5项目并完整接入

set -e

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  创建 test5 项目并接入到 ClearDebt Agent                            ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# 配置（你需要修改这些）
GITLAB_URL="git@gitlab.com:your-username/test5.git"  # 修改成你的GitLab地址
SONAR_TOKEN="your-sonar-token"  # 修改成你的Sonar token
PROJECT_DIR="/Users/perry/test5"

# ============================================
# 步骤1：创建代码仓库
# ============================================
echo "步骤1：创建代码仓库..."

if [ -d "$PROJECT_DIR" ]; then
    echo "  ⚠️  $PROJECT_DIR 已存在"
    read -p "  是否删除并重新创建? (y/N): " confirm
    if [ "$confirm" = "y" ]; then
        rm -rf "$PROJECT_DIR"
    else
        echo "  跳过创建"
        exit 0
    fi
fi

mkdir -p "$PROJECT_DIR/src"
cd "$PROJECT_DIR"

# 创建package.json
cat > package.json << 'EOF'
{
  "name": "test5",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "test": "echo \"No tests yet\""
  }
}
EOF

# 创建示例代码（包含代码异味）
cat > src/example.js << 'EOF'
// 包含一些代码异味，供Agent修复
export function processData(data) {
  let result = "initial";  // S1854: 无用赋值
  result = data;
  return result;
}

export function checkStatus(flag) {
  if (flag) {
    return true;
  } else {
    return true;  // S1871: 重复分支
  }
}

export function unusedVar() {
  const temp = 123;  // S1481: 未使用的变量
  return 456;
}
EOF

cat > src/utils.js << 'EOF'
export function formatName(name) {
  let formatted = "";
  formatted = name.toUpperCase();  // S1854: 无用赋值
  return formatted;
}

export function isSame(a, b) {
  if (a === a) {  // S6679: 自比较
    return true;
  }
  return a === b;
}
EOF

cat > README.md << 'EOF'
# Test5 Project

测试项目，用于ClearDebt Agent修复Sonar告警。

## 特点
- 包含多种代码异味
- 用于测试Agent的修复能力
- 已接入ClearDebt自动修复流程
EOF

cat > .gitignore << 'EOF'
node_modules/
.scannerwork/
coverage/
.DS_Store
EOF

echo "  ✓ 代码已创建"

# ============================================
# 步骤2：初始化Git并推送
# ============================================
echo ""
echo "步骤2：初始化Git并推送..."

git init
git config user.name "Perry"
git config user.email "perry@example.com"
git add .
git commit -m "Initial commit: test5 project with code smells for Agent testing"

echo "  Git仓库地址: $GITLAB_URL"
read -p "  是否推送到GitLab? (y/N): " push_confirm

if [ "$push_confirm" = "y" ]; then
    git remote add origin "$GITLAB_URL"
    git push -u origin main || git push -u origin master
    echo "  ✓ 已推送到GitLab"
else
    echo "  ⊝ 跳过推送（你可以稍后手动推送）"
    echo "    git remote add origin $GITLAB_URL"
    echo "    git push -u origin main"
fi

# ============================================
# 步骤3：创建Sonar项目并扫描
# ============================================
echo ""
echo "步骤3：创建Sonar项目并扫描..."

cat > sonar-project.properties << 'EOF'
sonar.projectKey=test5
sonar.projectName=test5
sonar.sources=src
sonar.sourceEncoding=UTF-8
sonar.javascript.node.maxspace=2048
EOF

read -p "  是否运行Sonar扫描? (y/N): " sonar_confirm

if [ "$sonar_confirm" = "y" ]; then
    if [ "$SONAR_TOKEN" = "your-sonar-token" ]; then
        echo "  ⚠️  请先修改脚本中的 SONAR_TOKEN"
        exit 1
    fi

    sonar-scanner \
      -Dsonar.host.url=http://localhost:9000 \
      -Dsonar.login="$SONAR_TOKEN"

    echo "  ✓ Sonar扫描完成"
    echo "  访问 http://localhost:9000/dashboard?id=test5 查看结果"
else
    echo "  ⊝ 跳过扫描（你可以稍后手动扫描）"
    echo "    sonar-scanner -Dsonar.host.url=http://localhost:9000 -Dsonar.login=YOUR_TOKEN"
fi

# ============================================
# 步骤4：添加到控制台绑定
# ============================================
echo ""
echo "步骤4：添加到控制台绑定..."

AGENT_DIR="/Users/perry/agent项目"
cd "$AGENT_DIR"

cat > /tmp/add_test5_binding.py << EOF
#!/usr/bin/env python3
import sys
import psycopg
import json

DB_URI = "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt"

try:
    with psycopg.connect(DB_URI) as conn:
        with conn.cursor() as cur:
            # 获取当前bindings
            cur.execute("SELECT bindings FROM settings WHERE id = 1")
            row = cur.fetchone()

            if row:
                bindings = json.loads(row[0]) if row[0] else []

                # 检查test5是否已存在
                if any(b.get("sonar_key") == "test5" for b in bindings):
                    print("  ⚠️  test5 已存在于bindings中")
                    sys.exit(0)

                # 添加test5
                new_binding = {
                    "sonar_key": "test5",
                    "gitlab_url": "$GITLAB_URL",
                    "branch": "main",
                    "read_only": False,
                    "provider": "gitlab"
                }

                bindings.append(new_binding)

                # 更新
                cur.execute(
                    "UPDATE settings SET bindings = %s WHERE id = 1",
                    (json.dumps(bindings),)
                )
                conn.commit()
                print("  ✓ test5 已添加到bindings")
            else:
                print("  ✗ settings表为空，需要先初始化")
                sys.exit(1)
except Exception as e:
    print(f"  ✗ 数据库操作失败: {e}")
    print("  你可能需要手动在控制台界面添加绑定")
    sys.exit(1)
EOF

python /tmp/add_test5_binding.py
rm /tmp/add_test5_binding.py

# ============================================
# 步骤5：验证接入
# ============================================
echo ""
echo "步骤5：验证接入..."

echo "  测试1: 列出test5的告警"
.venv/bin/python scripts/list_issues.py test5 2>/dev/null || echo "    ⚠️  无法列出告警（可能Sonar还没扫描）"

echo ""
echo "  测试2: 修复一个告警（需要手动运行）"
echo "    .venv/bin/python scripts/run_issue.py javascript:S1854 test5"

# ============================================
# 完成
# ============================================
echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ test5 项目创建完成                                               ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "项目位置: $PROJECT_DIR"
echo "GitLab: $GITLAB_URL"
echo "Sonar: http://localhost:9000/dashboard?id=test5"
echo ""
echo "下一步:"
echo "  1. 在GitLab查看代码"
echo "  2. 在Sonar查看告警"
echo "  3. 运行: cd /Users/perry/agent项目"
echo "  4. 运行: export \$(cat .env | xargs)"
echo "  5. 运行: .venv/bin/python scripts/run_issue.py javascript:S1854 test5"
echo "  6. 在LangSmith查看trace"
echo ""
