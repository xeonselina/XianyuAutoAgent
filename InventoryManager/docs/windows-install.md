# InventoryManager Windows 安装指南

本指南将帮助您在 Windows 系统上从零开始安装和运行 InventoryManager 库存管理系统。

## 🚀 快速开始

### 方式一：自动安装脚本（推荐）
0. **安装好 docker desktop并启动**
   - [下载安装](https://docs.docker.com/desktop/setup/install/windows-install/)

1. **下载项目**
   ```bash
   git clone <项目地址>
   cd InventoryManager
   ```

2. **以管理员身份运行 PowerShell**
   - 按 `Win + X`，选择"Windows PowerShell (管理员)"
   - 或按 `Win + R`，输入 `powershell`，按 `Ctrl + Shift + Enter`

3. **执行安装脚本**
   ```powershell
   Set-ExecutionPolicy Bypass -Scope Process -Force
   .\windows-setup.ps1
   ```

4. **配置项目环境**
   ```powershell
   .\windows-config.ps1
   ```

5. **启动项目**
   ```powershell
   .\windows-start.ps1
   ```

### 方式二：手动安装

如果自动脚本遇到问题，可以按照以下步骤手动安装。

## 📋 系统要求

- **操作系统**: Windows 10 或 Windows 11
- **内存**: 至少 4GB RAM（推荐 8GB+）
- **硬盘**: 至少 5GB 可用空间
- **网络**: 稳定的互联网连接用于下载依赖

## 🛠 手动安装步骤

### 1. 安装 Python 3.9

#### 方法 A：从官网下载
1. 访问 [Python 官网](https://www.python.org/downloads/)
2. 下载 Python 3.9.x 版本
3. 运行安装程序，**务必勾选 "Add Python to PATH"**
4. 选择 "Customize installation"，确保安装 pip

#### 方法 B：使用 Chocolatey
```powershell
# 安装 Chocolatey 包管理器
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# 安装 Python 3.9
choco install python39 -y
```

#### 验证安装
```cmd
python --version
pip --version
```

### 2. 安装 Git

#### 方法 A：从官网下载
1. 访问 [Git 官网](https://git-scm.com/download/win)
2. 下载并安装 Git for Windows

#### 方法 B：使用 Chocolatey
```powershell
choco install git -y
```

#### 验证安装
```cmd
git --version
```

### 3. 安装 Node.js（前端需要）

#### 方法 A：从官网下载
1. 访问 [Node.js 官网](https://nodejs.org/)
2. 下载 LTS 版本并安装

#### 方法 B：使用 Chocolatey
```powershell
choco install nodejs -y
```

#### 验证安装
```cmd
node --version
npm --version
```

### 4. 安装 Docker Desktop

#### 下载安装
1. 访问 [Docker Desktop 官网](https://www.docker.com/products/docker-desktop)
2. 下载 Docker Desktop for Windows
3. 安装完成后重启计算机
4. 启动 Docker Desktop
5. 在设置中启用 WSL 2 集成（如果使用 WSL）

#### 使用 Chocolatey
```powershell
choco install docker-desktop -y
```

#### 验证安装
```cmd
docker --version
docker-compose --version
```

### 5. 数据库选择

#### 选项 A：使用 Docker 运行 MySQL（推荐）
无需额外安装，项目中的 `docker-compose.yml` 已配置好 MySQL

#### 选项 B：本地安装 MySQL
1. 访问 [MySQL 官网](https://dev.mysql.com/downloads/mysql/)
2. 下载 MySQL Community Server
3. 安装时设置 root 密码

#### 使用 Chocolatey 安装 MySQL
```powershell
choco install mysql -y
```

## 🔧 项目配置

### 1. 克隆项目
```bash
git clone <项目地址>
cd InventoryManager
```

### 2. 创建 Python 虚拟环境
```bash
python -m venv venv
```

### 3. 激活虚拟环境
```bash
# Windows Command Prompt
venv\Scripts\activate

# PowerShell
venv\Scripts\Activate.ps1
```

### 4. 安装 Python 依赖
```bash
pip install -r requirements.txt
```

### 5. 安装前端依赖
```bash
cd frontend
npm install
cd ..
```

### 6. 配置环境变量

#### 复制配置文件
```bash
copy .env.example .env
```

#### 编辑 .env 文件
根据您的数据库配置修改以下内容：

```bash
# 本地 MySQL
DATABASE_URL=mysql+pymysql://root:your_password@localhost:3306/testdb

# 或使用 Docker MySQL
DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/testdb
```

### 7. 启动数据库

#### 使用 Docker（推荐）
```bash
docker-compose up -d db
```

#### 使用本地 MySQL
确保 MySQL 服务正在运行，并创建数据库：
```sql
CREATE DATABASE testdb;
```

### 8. 运行数据库迁移
```bash
python -m flask db upgrade
```

### 9. 构建前端
```bash
cd frontend
npm run build
cd ..
```

## 🚀 启动应用

### 开发模式
```bash
# 启动后端（在项目根目录）
python app.py

# 启动前端开发服务器（新开一个终端）
cd frontend
npm run dev
```

### 生产模式
```bash
# 使用提供的启动脚本
.\windows-start.ps1
```

## 🌐 访问应用

- **前端应用**: http://localhost:5173
- **后端API**: http://localhost:5001
- **API文档**: http://localhost:5001/api/docs

## 🛠 脚本说明

### `windows-setup.ps1`
自动安装脚本，包含以下功能：
- 安装 Chocolatey 包管理器
- 安装 Python 3.9、Git、Node.js、Docker Desktop
- 可选安装 MySQL
- 支持跳过特定组件的安装

**参数：**
- `-SkipPython`: 跳过 Python 安装
- `-SkipDocker`: 跳过 Docker 安装
- `-SkipGit`: 跳过 Git 安装
- `-SkipNode`: 跳过 Node.js 安装
- `-Help`: 显示帮助信息

### `windows-config.ps1`
项目环境配置脚本：
- 创建 Python 虚拟环境
- 安装 Python 和前端依赖
- 创建环境配置文件
- 运行数据库迁移

### `windows-start.ps1`
项目启动脚本：
- 启动数据库服务
- 启动后端服务
- 构建并服务前端应用

## 🔧 常见问题

### PowerShell 执行策略问题
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
```

### Python 虚拟环境激活失败
```powershell
# 设置执行策略
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Docker 启动失败
1. 确保 Docker Desktop 正在运行
2. 检查 Windows 功能中的"适用于 Linux 的 Windows 子系统"是否启用
3. 重启计算机后再次尝试

### 数据库连接失败
1. 检查 MySQL 服务是否运行
2. 验证 .env 文件中的数据库连接配置
3. 确保数据库用户有相应权限

### 端口冲突
如果默认端口被占用，可以在 .env 文件中修改：
```bash
APP_PORT=5002  # 修改后端端口
```

前端端口在 `frontend/vite.config.js` 中修改。

## 📝 开发建议

1. **使用虚拟环境**: 始终在激活的虚拟环境中工作
2. **定期备份数据库**: 使用 Docker 可以方便地备份数据卷
3. **代码版本控制**: 及时提交代码变更
4. **环境隔离**: 开发、测试、生产环境使用不同的配置

## 🆘 获取帮助

如果遇到问题，请：
1. 查看终端错误信息
2. 检查各组件是否正确安装
3. 验证环境配置文件
4. 查看应用日志文件

## 🔄 卸载

如果需要完全卸载：

1. **停止所有服务**
   ```bash
   .\windows-stop.ps1
   ```

2. **删除 Docker 容器和镜像**
   ```bash
   docker-compose down -v
   docker system prune -a
   ```

3. **删除虚拟环境**
   ```bash
   rmdir /s venv
   ```

4. **卸载通过 Chocolatey 安装的软件**
   ```powershell
   choco uninstall python39 git nodejs docker-desktop mysql
   ```

---

## 📄 许可证

本项目遵循相应的开源许可证。