# 创建 test5 项目并接入指南

由于我没有直接访问数据库的权限，我会提供完整的步骤指南，你可以按照这个来操作。

## 🎯 方案概述

创建test5项目需要3步：
1. 创建代码仓库并推送到GitLab
2. 在Sonar中创建项目并扫描
3. 在控制台绑定项目

---

## 步骤1：创建test5代码仓库

### 1.1 创建项目目录和代码

```bash
# 在与agent项目平级的位置创建test5
cd /Users/perry
mkdir test5
cd test5

# 初始化git
git init
git config user.name "Perry"
git config user.email "your-email@example.com"

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

# 创建示例代码（故意包含一些Sonar会报告的问题）
mkdir -p src

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

# 创建README
cat > README.md << 'EOF'
# Test5 Project

测试项目，用于ClearDebt Agent修复Sonar告警。

## 特点
- 包含多种代码异味
- 用于测试Agent的修复能力
EOF
```

### 1.2 推送到GitLab

```bash
# 添加remote（替换成你的GitLab地址）
git remote add origin git@gitlab.com:your-username/test5.git
# 或使用HTTP: git remote add origin https://gitlab.com/your-username/test5.git

# 提交代码
git add .
git commit -m "Initial commit: test5 project with code smells"

# 推送
git push -u origin main
# 如果main不存在，可能需要: git push -u origin master
```

**注意**：如果GitLab上还没有test5仓库，需要先在GitLab界面创建。

---

## 步骤2：在Sonar中创建项目

### 2.1 手动在Sonar界面创建

1. 访问 http://localhost:9000
2. 登录（admin/admin或你的凭证）
3. 点击 "Create Project"
4. 项目key: `test5`
5. 项目名称: `test5`
6. 点击创建

### 2.2 运行扫描

```bash
cd /Users/perry/test5

# 创建sonar-project.properties
cat > sonar-project.properties << 'EOF'
sonar.projectKey=test5
sonar.projectName=test5
sonar.sources=src
sonar.sourceEncoding=UTF-8
sonar.javascript.node.maxspace=2048
EOF

# 运行扫描
sonar-scanner \
  -Dsonar.host.url=http://localhost:9000 \
  -Dsonar.login=你的Sonar-token
```

扫描完成后，在Sonar界面应该能看到test5项目和它的告警。

---

## 步骤3：在控制台绑定项目

### 方式A：通过控制台界面（推荐）

1. 访问你的控制台: http://localhost:3000（或你的控制台地址）
2. 进入"项目绑定"或"Settings"页面
3. 添加新绑定：
   ```
   Sonar项目key: test5
   GitLab URL: https://gitlab.com/your-username/test5.git
   分支: main
   只读: false（允许开MR）
   ```
4. 保存

### 方式B：通过API（如果控制台提供）

```bash
curl -X POST http://localhost:3000/api/bindings \
  -H "Content-Type: application/json" \
  -d '{
    "sonar_key": "test5",
    "gitlab_url": "https://gitlab.com/your-username/test5.git",
    "branch": "main",
    "read_only": false
  }'
```

### 方式C：直接修改数据库（最后手段）

```python
# 使用Python脚本
cd /Users/perry/agent项目

cat > add_test5_binding.py << 'EOF'
#!/usr/bin/env python3
import psycopg

DB_URI = "postgresql://cleardebt:cleardebt@localhost:5433/cleardebt"

with psycopg.connect(DB_URI) as conn:
    with conn.cursor() as cur:
        # 获取当前bindings
        cur.execute("SELECT bindings FROM settings WHERE id = 1")
        row = cur.fetchone()
        
        if row:
            import json
            bindings = json.loads(row[0]) if row[0] else []
            
            # 添加test5
            new_binding = {
                "sonar_key": "test5",
                "gitlab_url": "https://gitlab.com/your-username/test5.git",
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
            print("✓ test5 binding added successfully")
        else:
            print("✗ No settings found")
EOF

python add_test5_binding.py
```

---

## 步骤4：验证接入

### 4.1 测试拉取告警

```bash
cd /Users/perry/agent项目

# 加载环境变量
export $(cat .env | xargs)

# 列出test5的告警
.venv/bin/python scripts/list_issues.py test5
```

你应该看到类似：

```
test5 的告警:
  1. javascript:S1854 @ src/example.js:3
  2. javascript:S1854 @ src/utils.js:3
  3. javascript:S1871 @ src/example.js:10
  4. javascript:S1481 @ src/example.js:17
  5. javascript:S6679 @ src/utils.js:8
```

### 4.2 测试修复一个告警

```bash
# 运行Agent修复
.venv/bin/python scripts/run_issue.py javascript:S1854 test5
```

### 4.3 在LangSmith查看trace

访问 https://smith.langchain.com，在 `cleardebt-dev` 项目中应该能看到test5的trace。

---

## 📋 检查清单

完成后检查：

- [ ] test5代码已推送到GitLab
- [ ] Sonar中能看到test5项目和告警
- [ ] 控制台中test5已绑定
- [ ] `list_issues.py test5` 能列出告警
- [ ] `run_issue.py` 能修复test5的告警
- [ ] LangSmith能看到test5的trace

---

## 🔧 故障排查

### 问题1：找不到test5项目

```bash
# 检查Sonar
curl -u admin:admin http://localhost:9000/api/projects/search?q=test5

# 检查绑定
# 在控制台界面查看，或
python -c "
from cleardebt.controls import load_controls
settings = load_controls()
import json
print(json.dumps(settings.get('bindings'), indent=2))
"
```

### 问题2：无法推送到GitLab

```bash
# 检查SSH key
ssh -T git@gitlab.com

# 或使用HTTP + Personal Access Token
git remote set-url origin https://oauth2:YOUR_TOKEN@gitlab.com/username/test5.git
```

### 问题3：Sonar扫描失败

```bash
# 检查sonar-scanner
sonar-scanner -v

# 检查Sonar服务
curl http://localhost:9000/api/system/status
```

---

## ✅ 完成

完成后，你就有了test5项目，可以用来：
- 测试Agent修复
- 演示完整流程
- 生成LangSmith trace
- 评测对比实验

**test5和test2/3/4的区别**：
- 新鲜的代码异味（5-6个问题）
- 独立的Git历史
- 可以随意实验，不影响其他项目
