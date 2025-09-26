# InventoryManager Windows 使用指南

本文档详细说明如何在 Windows 系统上快速部署和运行 InventoryManager 库存管理系统。

## 🎯 快速开始（推荐方式）

### 前提条件
- Windows 10 或 Windows 11
- 管理员权限

### 三步完成部署

#### 第一步：系统安装
以管理员身份打开 PowerShell，执行：

```powershell
# 设置执行策略（仅需一次）
Set-ExecutionPolicy Bypass -Scope Process -Force

# 运行自动安装脚本
.\windows-setup.ps1
```

**安装内容：**
- Python 3.9
- Git 版本控制
- Node.js 前端环境
- Docker Desktop 容器平台
- MySQL 数据库（可选）

#### 第二步：项目配置
```powershell
# 配置项目环境
.\windows-config.ps1
```

**配置内容：**
- 创建 Python 虚拟环境
- 安装后端依赖包
- 安装前端依赖包
- 创建环境配置文件
- 运行数据库迁移

#### 第三步：启动服务
```powershell
# 启动完整项目
.\windows-start.ps1
```

**启动服务：**
- MySQL 数据库
- Flask 后端 API
- Vue.js 前端界面

## 🌐 访问地址

启动成功后，可以通过以下地址访问：

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端应用 | http://localhost:5173 | 主界面（开发模式） |
| 后端API | http://localhost:5001 | REST API 服务 |
| API文档 | http://localhost:5001/api/docs | Swagger API 文档 |

## 🛠 脚本详细说明

### `windows-setup.ps1` - 系统安装脚本

**基本用法：**
```powershell
.\windows-setup.ps1
```

**高级选项：**
```powershell
# 跳过特定组件
.\windows-setup.ps1 -SkipDocker          # 不安装 Docker
.\windows-setup.ps1 -SkipPython          # 不安装 Python
.\windows-setup.ps1 -SkipGit             # 不安装 Git
.\windows-setup.ps1 -SkipNode            # 不安装 Node.js

# 查看帮助
.\windows-setup.ps1 -Help
```

**功能说明：**
- ✅ 检测并安装缺失的组件
- ✅ 自动配置环境变量
- ✅ 支持跳过已安装的组件
- ✅ 提供详细的安装反馈

### `windows-config.ps1` - 项目配置脚本

**基本用法：**
```powershell
.\windows-config.ps1
```

**高级选项：**
```powershell
# 跳过特定配置
.\windows-config.ps1 -SkipVenv           # 不创建虚拟环境
.\windows-config.ps1 -SkipFrontend       # 不安装前端依赖
.\windows-config.ps1 -SkipMigration      # 不运行数据库迁移

# 查看帮助
.\windows-config.ps1 -Help
```

**配置流程：**
1. 🔍 检查项目目录和 Python 环境
2. 📦 创建 Python 虚拟环境
3. ⬇️ 安装 Python 依赖包
4. 🎨 安装前端依赖包
5. ⚙️ 创建 .env 配置文件
6. 🗄️ 运行数据库迁移

**数据库选择：**
运行时会提示选择数据库类型：
1. **Docker MySQL**（推荐）- 自动管理，自动配置 .env 文件，包含连接测试
2. **本地 MySQL** - 交互式配置，会要求输入连接信息并自动更新 .env 文件
3. **SQLite** - 轻量级，适合测试，自动配置 .env 文件
4. **跳过配置** - 稍后手动配置

**智能配置功能：**
- ✅ 自动检测并更新 .env 文件中的 `DATABASE_URL`
- ✅ Docker MySQL：自动启动容器并测试连接
- ✅ 本地 MySQL：交互式收集连接信息（主机、端口、用户名、密码、数据库名）
- ✅ 连接验证：自动测试数据库连接是否成功
- ✅ 错误处理：连接失败时提供故障排除建议

### `windows-start.ps1` - 项目启动脚本

**基本用法：**
```powershell
.\windows-start.ps1
```

**启动模式：**
```powershell
# 开发模式（默认）
.\windows-start.ps1

# 生产模式
.\windows-start.ps1 -Production

# 仅启动后端
.\windows-start.ps1 -BackendOnly

# 仅启动前端
.\windows-start.ps1 -FrontendOnly

# 跳过数据库启动
.\windows-start.ps1 -SkipDatabase

# 查看帮助
.\windows-start.ps1 -Help
```

**启动流程：**
1. 🔍 检查项目环境
2. 🗄️ 启动数据库服务
3. 🚀 启动后端服务
4. 🎨 启动前端服务
5. 📊 持续监控服务状态

**开发模式 vs 生产模式：**

| 功能 | 开发模式 | 生产模式 |
|------|----------|----------|
| 前端 | Vite 开发服务器 | 构建后通过后端服务 |
| 热重载 | ✅ 支持 | ❌ 不支持 |
| 调试信息 | ✅ 详细 | ❌ 精简 |
| 性能 | 🔄 实时编译 | ⚡ 预编译优化 |

### `windows-stop.ps1` - 项目停止脚本

**基本用法：**
```powershell
.\windows-stop.ps1
```

**高级选项：**
```powershell
# 保留数据库运行
.\windows-stop.ps1 -KeepDatabase

# 查看帮助
.\windows-stop.ps1 -Help
```

**停止流程：**
1. 🛑 停止后端 Flask 进程
2. 🛑 停止前端 Node.js 进程
3. 🛑 停止后台 PowerShell 作业
4. 🛑 停止 Docker 容器
5. 🧹 清理临时文件
6. 🔍 检查端口释放情况

## 🔧 环境配置

### .env 文件配置

项目配置文件位于根目录的 `.env` 文件：

```bash
# 应用基础配置
FLASK_ENV=development
FLASK_APP=app.py
SECRET_KEY=your-secret-key-change-in-production

# 数据库配置（根据选择修改）
# Docker MySQL
DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/testdb

# 本地 MySQL
# DATABASE_URL=mysql+pymysql://root:your_password@localhost:3306/testdb

# SQLite（测试用）
# DATABASE_URL=sqlite:///inventory_management.db

# 应用端口
APP_PORT=5001
APP_HOST=0.0.0.0
```

### 端口配置

**后端端口修改：**
```bash
# 在 .env 文件中修改
APP_PORT=5002
```

**前端端口修改：**
```javascript
// 在 frontend/vite.config.js 中修改
export default defineConfig({
  server: {
    port: 5174
  }
})
```

## 🚀 日常开发工作流

### 开始工作
```powershell
# 启动完整开发环境
.\windows-start.ps1

# 或仅启动后端进行API开发
.\windows-start.ps1 -BackendOnly
```

### 结束工作
```powershell
# 停止所有服务
.\windows-stop.ps1

# 或保留数据库，仅停止应用
.\windows-stop.ps1 -KeepDatabase
```

### 重启服务
```powershell
# 快速重启
.\windows-stop.ps1 -KeepDatabase
.\windows-start.ps1
```

## 📊 监控和调试

### 查看日志
```powershell
# 应用日志
Get-Content .\logs\inventory_service.log -Tail 50

# Docker 容器日志
docker logs inventorymanager_db_1
```

### 检查服务状态
```powershell
# 检查端口占用
netstat -ano | findstr :5001
netstat -ano | findstr :5173
netstat -ano | findstr :3306

# 检查进程
Get-Process python
Get-Process node
```

### 数据库管理
```powershell
# 进入 MySQL 容器
docker exec -it inventorymanager_db_1 mysql -uroot -p123456

# 备份数据库
docker exec inventorymanager_db_1 mysqldump -uroot -p123456 testdb > backup.sql

# 恢复数据库
docker exec -i inventorymanager_db_1 mysql -uroot -p123456 testdb < backup.sql
```

## 🔄 更新和维护

### 更新依赖
```powershell
# 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 更新 Python 依赖
pip install -r requirements.txt --upgrade

# 更新前端依赖
cd frontend
npm update
cd ..
```

### 数据库迁移
```powershell
# 生成新迁移
.\venv\Scripts\python.exe -m flask db migrate -m "描述变更"

# 应用迁移
.\venv\Scripts\python.exe -m flask db upgrade

# 回滚迁移
.\venv\Scripts\python.exe -m flask db downgrade
```

## ❗ 常见问题和解决方案

### PowerShell 执行策略错误
```powershell
# 问题：无法执行脚本
# 解决：设置执行策略
Set-ExecutionPolicy Bypass -Scope Process -Force
```

### Docker 启动失败
```powershell
# 问题：Docker 命令不可用
# 解决：
# 1. 启动 Docker Desktop
# 2. 重启计算机
# 3. 检查 WSL 2 是否启用
```

### 端口被占用
```powershell
# 问题：端口 5001 已被占用
# 解决：查找并停止占用进程
netstat -ano | findstr :5001
taskkill /PID <进程ID> /F
```

### 虚拟环境激活失败
```powershell
# 问题：无法激活虚拟环境
# 解决：设置执行策略
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 数据库连接失败
```bash
# 问题：无法连接数据库
# 解决：检查配置
# 1. 确认数据库服务运行中
# 2. 验证 .env 中的 DATABASE_URL
# 3. 检查防火墙设置
```

## 🎯 性能优化建议

### 开发环境优化
1. **SSD存储** - 将项目放在SSD上提高IO性能
2. **内存配置** - 建议8GB+内存用于Docker和Node.js
3. **防病毒排除** - 将项目目录加入防病毒软件白名单

### 生产环境部署
```powershell
# 构建优化版本
.\windows-start.ps1 -Production

# 配置反向代理（推荐使用 Nginx）
# 启用GZIP压缩
# 配置静态文件缓存
```

## 📞 技术支持

遇到问题时，请按以下顺序排查：

1. **查看错误日志** - 检查终端输出和日志文件
2. **验证环境** - 确认所有组件正确安装
3. **重启服务** - 尝试完全重启所有服务
4. **检查网络** - 确认防火墙和端口设置
5. **查看文档** - 参考本文档和相关组件文档

---

**版本信息**
- InventoryManager: 最新版
- Python: 3.9+
- Node.js: LTS版本
- Docker: 最新版本

**最后更新**: 2025年9月