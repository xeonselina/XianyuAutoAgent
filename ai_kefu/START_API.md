# API 服务启动指南

## 快速启动

### 方式 1: 使用 Makefile（推荐）

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
make run-api
```

### 方式 2: 直接使用 Python

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
PYTHONPATH=/Users/jimmypan/git_repo/XianyuAutoAgent:$PYTHONPATH \
  python3 -m uvicorn ai_kefu.api.main:app --host 0.0.0.0 --port 8000
```

### 方式 3: 使用虚拟环境（生产环境推荐）

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu

# 创建虚拟环境（首次运行）
make install

# 启动服务
./venv/bin/uvicorn ai_kefu.api.main:app --host 0.0.0.0 --port 8000
```

## 验证服务

启动后，访问：

- **根路径**: http://localhost:8000/
- **API 文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/health

```bash
# 测试连接
curl http://localhost:8000/

# 预期输出
{"message":"AI Customer Service Agent API","version":"1.0.0","status":"running"}
```

## 可用命令

查看所有可用命令：

```bash
make help
```

常用命令：

| 命令 | 说明 |
|------|------|
| `make run-api` | 启动 API 服务 |
| `make run-xianyu` | 启动闲鱼客服机器人 |
| `make init-knowledge` | 初始化知识库 |
| `make check-env` | 检查环境配置 |
| `make install` | 安装依赖到虚拟环境 |
| `make dev` | 启动开发服务器（热重载） |
| `make test` | 运行测试 |
| `make clean` | 清理临时文件 |

## 配置说明

API 服务依赖以下配置（`.env` 文件）：

### 必需配置

```ini
# 通义千问 API Key
API_KEY=sk-your-api-key-here

# MySQL 配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=xianyu_conversations
```

### 可选配置

```ini
# API 服务配置
API_HOST=0.0.0.0
API_PORT=8000

# Redis 配置（用于会话管理）
REDIS_URL=redis://localhost:6379

# 模型配置
MODEL_NAME=qwen3.5-plus
```

## 启动前检查

在启动 API 服务前，请确保：

### 1. 环境配置检查

```bash
make check-env
```

应该看到：
```
✅ MySQL 连接成功！
✅ API Key 已配置
✅ 所有配置检查通过！
```

### 2. 知识库初始化

```bash
make init-knowledge
```

应该看到：
```
✅ 成功添加 7/7 条知识
```

### 3. Redis 服务启动（可选）

```bash
# macOS
brew services start redis

# Linux
sudo systemctl start redis

# Docker
docker run -d -p 6379:6379 redis:7-alpine
```

## 常见问题

### Q1: ModuleNotFoundError: No module named 'ai_kefu'

**原因**：PYTHONPATH 未正确设置

**解决**：
```bash
# 使用 make 命令（自动设置 PYTHONPATH）
make run-api

# 或手动设置
export PYTHONPATH=/Users/jimmypan/git_repo/XianyuAutoAgent:$PYTHONPATH
```

### Q2: 端口被占用

**错误信息**：
```
Address already in use
```

**解决**：
```bash
# 查看占用端口的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>

# 或使用其他端口
python3 -m uvicorn ai_kefu.api.main:app --port 8001
```

### Q3: MySQL 连接失败

**解决**：
1. 确认 MySQL 已启动
2. 检查 `.env` 中的配置
3. 运行 `make check-env` 诊断

### Q4: API Key 无效

**解决**：
1. 访问 https://dashscope.console.aliyun.com/
2. 检查 API Key 是否正确
3. 确认账户有可用额度

## 开发模式

如果要在开发模式下运行（支持热重载）：

```bash
make dev
```

文件修改后会自动重启服务。

## 生产部署

生产环境建议：

1. **使用虚拟环境**：
   ```bash
   make install
   source venv/bin/activate
   ```

2. **使用进程管理器**：
   ```bash
   # 使用 systemd
   sudo systemctl start ai-kefu

   # 或使用 supervisor
   supervisorctl start ai-kefu
   ```

3. **配置反向代理**（Nginx）：
   ```nginx
   location / {
       proxy_pass http://localhost:8000;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
   }
   ```

## 停止服务

```bash
# 如果在前台运行，按 Ctrl+C

# 如果在后台运行
pkill -f "uvicorn ai_kefu.api.main"

# 或查找进程 ID
lsof -i :8000
kill -9 <PID>
```

## 获取帮助

- 查看日志文件获取详细错误信息
- 运行 `make check-env` 诊断配置问题
- 查看 [README.md](README.md) 获取更多信息
- 提交 Issue 到项目仓库
