# InventoryManager Windows 自动安装脚本
# 运行方式: 以管理员身份运行 PowerShell，然后执行此脚本
# PowerShell -ExecutionPolicy Bypass -File windows-setup.ps1

param(
    [switch]$SkipPython,
    [switch]$SkipDocker,
    [switch]$SkipGit,
    [switch]$SkipNode,
    [switch]$Help
)

if ($Help) {
    Write-Host "InventoryManager Windows 自动安装脚本" -ForegroundColor Green
    Write-Host "参数说明:"
    Write-Host "  -SkipPython  跳过Python安装"
    Write-Host "  -SkipDocker  跳过Docker安装"
    Write-Host "  -SkipGit     跳过Git安装"
    Write-Host "  -SkipNode    跳过Node.js安装"
    Write-Host "  -Help        显示帮助信息"
    Write-Host ""
    Write-Host "使用示例:"
    Write-Host "  .\windows-setup.ps1                    # 完整安装"
    Write-Host "  .\windows-setup.ps1 -SkipDocker        # 跳过Docker安装"
    exit
}

# 检查管理员权限
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Error "此脚本需要管理员权限运行！请以管理员身份运行PowerShell"
    pause
    exit 1
}

Write-Host "=== InventoryManager Windows 安装脚本 ===" -ForegroundColor Green
Write-Host "开始自动安装所需组件..." -ForegroundColor Yellow

# 启用TLS 1.2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 安装Chocolatey包管理器
Write-Host "`n正在检查并安装 Chocolatey 包管理器..." -ForegroundColor Cyan
if (!(Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "安装 Chocolatey..."
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

    # 刷新环境变量
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
} else {
    Write-Host "Chocolatey 已安装" -ForegroundColor Green
}

# 安装Git
if (!$SkipGit) {
    Write-Host "`n正在检查并安装 Git..." -ForegroundColor Cyan
    if (!(Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "安装 Git..."
        choco install git -y
        # 刷新环境变量
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    } else {
        Write-Host "Git 已安装: $(git --version)" -ForegroundColor Green
    }
} else {
    Write-Host "跳过 Git 安装" -ForegroundColor Yellow
}

# 安装Python 3.9
if (!$SkipPython) {
    Write-Host "`n正在检查并安装 Python 3.9..." -ForegroundColor Cyan
    $pythonVersion = python --version 2>$null
    if ($LASTEXITCODE -ne 0 -or !$pythonVersion.Contains("3.9")) {
        Write-Host "安装 Python 3.9..."
        choco install python39 -y
        # 刷新环境变量
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

        # 验证安装
        Start-Sleep 5
        $pythonVersion = python --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Python 安装成功: $pythonVersion" -ForegroundColor Green
        } else {
            Write-Error "Python 安装失败，请手动安装 Python 3.9"
        }
    } else {
        Write-Host "Python 已安装: $pythonVersion" -ForegroundColor Green
    }

    # 升级pip
    Write-Host "升级 pip..."
    python -m pip install --upgrade pip
} else {
    Write-Host "跳过 Python 安装" -ForegroundColor Yellow
}

# 安装Node.js (前端需要)
if (!$SkipNode) {
    Write-Host "`n正在检查并安装 Node.js..." -ForegroundColor Cyan
    if (!(Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "安装 Node.js..."
        choco install nodejs -y
        # 刷新环境变量
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    } else {
        Write-Host "Node.js 已安装: $(node --version)" -ForegroundColor Green
    }
} else {
    Write-Host "跳过 Node.js 安装" -ForegroundColor Yellow
}

# 安装Docker Desktop
if (!$SkipDocker) {
    Write-Host "`n正在检查并安装 Docker Desktop..." -ForegroundColor Cyan
    if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "安装 Docker Desktop..."
        choco install docker-desktop -y
        Write-Host "Docker Desktop 安装完成，请重启计算机后手动启动 Docker Desktop" -ForegroundColor Yellow
        Write-Host "重启后，请确保在 Docker Desktop 设置中启用 WSL 2 集成" -ForegroundColor Yellow
    } else {
        Write-Host "Docker 已安装: $(docker --version)" -ForegroundColor Green
    }
} else {
    Write-Host "跳过 Docker 安装" -ForegroundColor Yellow
}

# 安装MySQL (可选，也可以用Docker)
Write-Host "`n正在检查并安装 MySQL..." -ForegroundColor Cyan
$mysqlService = Get-Service -Name "MySQL*" -ErrorAction SilentlyContinue
if (!$mysqlService) {
    $installMySQL = Read-Host "是否安装 MySQL Server？(y/n，推荐使用Docker运行MySQL)"
    if ($installMySQL -eq "y" -or $installMySQL -eq "Y") {
        Write-Host "安装 MySQL Server..."
        choco install mysql -y
        Write-Host "MySQL 安装完成。默认root密码为空，请及时设置密码。" -ForegroundColor Yellow
    }
} else {
    Write-Host "MySQL 服务已安装" -ForegroundColor Green
}

Write-Host "`n=== 基础组件安装完成 ===" -ForegroundColor Green

# 检查是否在项目目录中
$currentPath = Get-Location
$isProjectDir = Test-Path "app.py" -PathType Leaf

if (!$isProjectDir) {
    Write-Host "`n请导航到 InventoryManager 项目根目录，然后运行项目配置脚本" -ForegroundColor Yellow
    Write-Host "配置命令: .\windows-config.ps1" -ForegroundColor Cyan
} else {
    Write-Host "`n检测到项目文件，开始配置项目环境..." -ForegroundColor Cyan

    # 创建Python虚拟环境
    Write-Host "创建Python虚拟环境..."
    python -m venv venv

    # 激活虚拟环境并安装依赖
    Write-Host "激活虚拟环境并安装Python依赖..."
    & ".\venv\Scripts\Activate.ps1"
    pip install -r requirements.txt

    # 安装前端依赖
    Write-Host "安装前端依赖..."
    Set-Location frontend
    npm install
    Set-Location ..

    # 创建.env文件（如果不存在）
    if (!(Test-Path ".env")) {
        Write-Host "创建.env配置文件..."
        Copy-Item ".env.example" ".env" -ErrorAction SilentlyContinue
        Write-Host "请编辑 .env 文件配置数据库连接" -ForegroundColor Yellow
    }

    Write-Host "`n项目配置完成！" -ForegroundColor Green
    Write-Host "后续步骤:" -ForegroundColor Cyan
    Write-Host "1. 编辑 .env 文件配置数据库连接"
    Write-Host "2. 启动数据库服务 (Docker 或 MySQL)"
    Write-Host "3. 运行数据库迁移: python -m flask db upgrade"
    Write-Host "4. 启动应用: .\windows-start.ps1"
}

Write-Host "`n安装脚本执行完成！" -ForegroundColor Green
Write-Host "如果安装了Docker，请重启计算机后手动启动Docker Desktop" -ForegroundColor Yellow

# 显示下一步操作
Write-Host "`n=== 下一步操作 ===" -ForegroundColor Cyan
Write-Host "1. 如果安装了Docker，请重启计算机"
Write-Host "2. 启动Docker Desktop（如果安装了）"
Write-Host "3. 运行项目配置脚本: .\windows-config.ps1"
Write-Host "4. 运行项目启动脚本: .\windows-start.ps1"

pause