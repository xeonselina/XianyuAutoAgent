# 知识库初始化指南

本指南帮助您完成租赁业务知识库的初始化配置。

## 前置要求

### 1. MySQL 数据库

确保 MySQL 已安装并运行：

```bash
# macOS
brew services start mysql

# Linux
sudo systemctl start mysql

# 检查 MySQL 状态
mysql -u root -p -e "SELECT VERSION();"
```

### 2. 通义千问 API Key

需要从阿里云获取 API Key：

1. 访问 [DashScope 控制台](https://dashscope.console.aliyun.com/)
2. 登录阿里云账号
3. 创建 API Key
4. 复制生成的 Key（格式：`sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）

## 配置步骤

### 第 1 步：编辑 `.env` 文件

```bash
nano /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/.env
```

添加或修改以下配置：

```ini
# 通义千问 API Key（必填）
API_KEY=sk-your-actual-api-key-here

# MySQL 配置（必填）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=xianyu_conversations
```

**重要**：
- `API_KEY` 必须是有效的通义千问 API Key
- `MYSQL_USER` 通常是 `root`
- `MYSQL_PASSWORD` 是你的 MySQL 密码（如果没有设置密码，可以留空）

### 第 2 步：检查环境配置

运行环境检查脚本：

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
python3 scripts/check_env.py
```

预期输出：
```
✅ MySQL 连接成功！
✅ API Key 已配置
✅ 所有配置检查通过！
```

如果有错误，请根据提示修复配置。

### 第 3 步：初始化知识库

运行初始化脚本：

```bash
python3 scripts/init_rental_knowledge.py
```

脚本会自动：
1. ✅ 检查 API Key 是否有效
2. ✅ 检查数据库是否存在，不存在则创建
3. ✅ 检查表是否存在，不存在则创建
4. ✅ 添加 7 条租赁业务知识

预期输出：
```
============================================================
手机租赁业务知识库初始化
============================================================

检查通义千问 API Key...
✅ API Key 已配置: sk-xxxxxxxx...xxxx

检查 MySQL 数据库...
✅ 数据库 'xianyu_conversations' 已存在
检查数据库表...
✅ 表 'knowledge_entries' 已存在

初始化知识库存储 (路径: ./chroma_data)...
当前知识库条目数: 0

准备添加 7 条租赁业务知识...

处理: 租赁定价规则 (租赁定价)...
  生成向量嵌入...
  添加到知识库...
  ✅ 成功添加: 租赁定价规则

... (省略其他条目)

============================================================
初始化完成！成功添加 7/7 条知识
知识库总条目数: 7
============================================================
```

## 常见问题

### Q1: API Key 错误

**错误信息**：
```
❌ 向量嵌入生成失败: RetryError[...]
```

**解决方案**：
1. 确认 `.env` 文件中的 `API_KEY` 不是占位符 `your_api_key_here`
2. 检查 API Key 是否有效（登录 DashScope 控制台查看）
3. 确认账户有足够的额度（新账户通常有免费额度）

### Q2: MySQL 连接失败

**错误信息**：
```
❌ MySQL 连接失败: (2003, "Can't connect to MySQL server...")
```

**解决方案**：
1. 确认 MySQL 服务已启动
2. 检查端口是否为 3306
3. 验证用户名和密码是否正确

### Q3: 表不存在

**错误信息**：
```
ERROR | "Table 'xianyu_conversations.knowledge_entries' doesn't exist"
```

**解决方案**：
脚本已更新，会自动创建表。如果仍然失败：
```bash
# 手动创建表
mysql -u root -p xianyu_conversations < migrations/002_create_knowledge_entries_table.sql
```

### Q4: 知识库已存在

如果知识库已经初始化过，想要重新初始化：

```bash
# 清空知识库
mysql -u root -p -e "TRUNCATE TABLE xianyu_conversations.knowledge_entries;"

# 删除 ChromaDB 数据
rm -rf chroma_data/

# 重新初始化
python3 scripts/init_rental_knowledge.py
```

## 验证知识库

初始化成功后，可以测试知识库检索：

```bash
python3 -c "
from ai_kefu.tools.knowledge_search import knowledge_search
result = knowledge_search('租赁定价规则')
print(result)
"
```

## 下一步

知识库初始化完成后，可以：

1. 启动 API 服务：
   ```bash
   make run-api
   ```

2. 测试 API：
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"query": "手机租赁如何定价？"}'
   ```

## 获取帮助

如果遇到问题：
1. 查看 [README.md](README.md) 获取更多信息
2. 运行 `python3 scripts/check_env.py` 诊断配置
3. 提交 Issue 到项目仓库
