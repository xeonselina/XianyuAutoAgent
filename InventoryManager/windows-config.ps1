# InventoryManager Windows 项目配置脚本
# 在项目根目录中运行此脚本来配置开发环境

param(
    [switch]$SkipVenv,
    [switch]$SkipFrontend,
    [switch]$SkipMigration,
    [switch]$Help
)

if ($Help) {
    Write-Host "InventoryManager Windows 项目配置脚本" -ForegroundColor Green
    Write-Host "参数说明:"
    Write-Host "  -SkipVenv       跳过Python虚拟环境创建"
    Write-Host "  -SkipFrontend   跳过前端依赖安装"
    Write-Host "  -SkipMigration  跳过数据库迁移"
    Write-Host "  -Help           显示帮助信息"
    Write-Host ""
    Write-Host "使用示例:"
    Write-Host "  .\windows-config.ps1                    # 完整配置"
    Write-Host "  .\windows-config.ps1 -SkipMigration     # 跳过数据库迁移"
    exit
}

Write-Host "=== InventoryManager 项目配置脚本 ===" -ForegroundColor Green

# 检查是否在项目目录
if (!(Test-Path "app.py" -PathType Leaf)) {
    Write-Error "请在 InventoryManager 项目根目录中运行此脚本！"
    Write-Host "当前目录: $(Get-Location)" -ForegroundColor Red
    Write-Host "请导航到包含 app.py 文件的目录" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "项目目录确认: $(Get-Location)" -ForegroundColor Green

# 检查Python是否已安装
Write-Host "`n检查 Python 安装..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Python 版本: $pythonVersion" -ForegroundColor Green
    } else {
        Write-Error "Python 未安装或未添加到 PATH。请先运行 windows-setup.ps1"
        exit 1
    }
} catch {
    Write-Error "Python 未安装。请先运行 windows-setup.ps1"
    exit 1
}

# 创建Python虚拟环境
if (!$SkipVenv) {
    Write-Host "`n配置 Python 虚拟环境..." -ForegroundColor Cyan
    if (Test-Path "venv" -PathType Container) {
        Write-Host "虚拟环境已存在" -ForegroundColor Yellow
        $recreateVenv = Read-Host "是否重新创建虚拟环境？(y/n)"
        if ($recreateVenv -eq "y" -or $recreateVenv -eq "Y") {
            Write-Host "删除现有虚拟环境..."
            Remove-Item -Recurse -Force "venv" -ErrorAction SilentlyContinue
            Write-Host "创建新的虚拟环境..."
            python -m venv venv
        }
    } else {
        Write-Host "创建 Python 虚拟环境..."
        python -m venv venv
    }

    # 检查虚拟环境是否创建成功
    if (!(Test-Path "venv\Scripts\python.exe")) {
        Write-Error "虚拟环境创建失败！"
        exit 1
    }

    Write-Host "虚拟环境创建成功" -ForegroundColor Green
} else {
    Write-Host "跳过虚拟环境创建" -ForegroundColor Yellow
}

# 激活虚拟环境并安装Python依赖
if (!$SkipVenv) {
    Write-Host "`n激活虚拟环境并安装 Python 依赖..." -ForegroundColor Cyan

    # 检查requirements.txt是否存在
    if (!(Test-Path "requirements.txt")) {
        Write-Error "requirements.txt 文件不存在！"
        exit 1
    }

    try {
        # 激活虚拟环境
        & ".\venv\Scripts\Activate.ps1"

        # 升级pip
        Write-Host "升级 pip..."
        & ".\venv\Scripts\python.exe" -m pip install --upgrade pip

        # 安装依赖
        Write-Host "安装 Python 依赖包..."
        & ".\venv\Scripts\pip.exe" install -r requirements.txt

        if ($LASTEXITCODE -eq 0) {
            Write-Host "Python 依赖安装成功" -ForegroundColor Green
        } else {
            Write-Error "Python 依赖安装失败"
            exit 1
        }
    } catch {
        Write-Error "安装 Python 依赖时出错: $_"
        exit 1
    }
}

# 安装前端依赖
if (!$SkipFrontend) {
    Write-Host "`n安装前端依赖..." -ForegroundColor Cyan

    if (Test-Path "frontend" -PathType Container) {
        # 检查Node.js是否已安装
        if (!(Get-Command node -ErrorAction SilentlyContinue)) {
            Write-Error "Node.js 未安装。请先运行 windows-setup.ps1"
            exit 1
        }

        $nodeVersion = node --version
        Write-Host "Node.js 版本: $nodeVersion" -ForegroundColor Green

        # 进入前端目录并安装依赖
        Push-Location frontend
        try {
            if (Test-Path "package.json") {
                Write-Host "安装前端依赖包..."
                npm install

                if ($LASTEXITCODE -eq 0) {
                    Write-Host "前端依赖安装成功" -ForegroundColor Green
                } else {
                    Write-Error "前端依赖安装失败"
                    Pop-Location
                    exit 1
                }
            } else {
                Write-Warning "frontend/package.json 不存在"
            }
        } catch {
            Write-Error "安装前端依赖时出错: $_"
            Pop-Location
            exit 1
        } finally {
            Pop-Location
        }
    } else {
        Write-Warning "frontend 目录不存在，跳过前端依赖安装"
    }
} else {
    Write-Host "跳过前端依赖安装" -ForegroundColor Yellow
}

# 配置环境变量文件
Write-Host "`n配置环境变量..." -ForegroundColor Cyan
if (!(Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "从 .env.example 创建 .env 文件..."
        Copy-Item ".env.example" ".env"
        Write-Host ".env 文件已创建" -ForegroundColor Green
    } else {
        Write-Host "创建默认 .env 文件..."
        $defaultEnv = @"
# InventoryManager 环境配置
FLASK_ENV=development
FLASK_APP=app.py
SECRET_KEY=your-secret-key-change-in-production
API_KEY=your-api-key-change-in-production

# 数据库配置 - 请根据您的环境修改
# 本地MySQL
DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/testdb

# Docker MySQL (如果使用docker-compose)
# DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/testdb

# SQLite (测试用)
# DATABASE_URL=sqlite:///inventory_management.db

# 应用配置
APP_PORT=5001
APP_HOST=0.0.0.0

# 其他配置
LOG_LEVEL=INFO
LOG_FILE=logs/inventory_service.log
TIMEZONE=Asia/Shanghai
"@
        $defaultEnv | Out-File -FilePath ".env" -Encoding utf8
        Write-Host "默认 .env 文件已创建" -ForegroundColor Green
    }

    Write-Host "请根据您的环境编辑 .env 文件中的配置" -ForegroundColor Yellow
    Write-Host "特别是数据库连接配置 DATABASE_URL" -ForegroundColor Yellow
} else {
    Write-Host ".env 文件已存在" -ForegroundColor Green
}

# 创建日志目录
Write-Host "`n创建必要的目录..." -ForegroundColor Cyan
$directories = @("logs", "uploads")
foreach ($dir in $directories) {
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
        Write-Host "创建目录: $dir" -ForegroundColor Green
    } else {
        Write-Host "目录已存在: $dir" -ForegroundColor Yellow
    }
}

# 数据库迁移
if (!$SkipMigration) {
    Write-Host "`n数据库配置..." -ForegroundColor Cyan

    # 检查数据库连接
    $dbConnected = $false

    # 询问用户数据库类型
    Write-Host "请选择数据库类型:"
    Write-Host "1. Docker MySQL (推荐)"
    Write-Host "2. 本地 MySQL"
    Write-Host "3. SQLite (测试用)"
    Write-Host "4. 跳过数据库配置"

    $dbChoice = Read-Host "请选择 (1-4)"

    switch ($dbChoice) {
        "1" {
            Write-Host "配置 Docker MySQL..." -ForegroundColor Cyan
            # 检查docker是否可用
            if (Get-Command docker -ErrorAction SilentlyContinue) {
                # 更新.env文件使用Docker MySQL（匹配docker-compose.yml配置）
                # Docker MySQL: root密码=rootpassword, 数据库名=inventory_db
                Write-Host "更新 .env 文件中的数据库配置..."
                $envContent = Get-Content ".env" | ForEach-Object {
                    if ($_ -match "^DATABASE_URL_HOST=") {
                        "DATABASE_URL_HOST=mysql+pymysql://root:rootpassword@localhost:3306/inventory_db"
                    } elseif ($_ -match "^DATABASE_URL=") {
                        "DATABASE_URL=mysql+pymysql://root:rootpassword@localhost:3306/inventory_db"
                    } else {
                        $_
                    }
                }
                # 如果没有DATABASE_URL_HOST，在第一个DATABASE_URL前面添加
                if (-not ($envContent -match "^DATABASE_URL_HOST=")) {
                    $newContent = @()
                    $added = $false
                    foreach ($line in $envContent) {
                        if (-not $added -and $line -match "^DATABASE_URL=") {
                            $newContent += "# Windows本地环境连接Docker MySQL（优先使用）"
                            $newContent += "DATABASE_URL_HOST=mysql+pymysql://root:rootpassword@localhost:3306/inventory_db"
                            $newContent += ""
                            $added = $true
                        }
                        $newContent += $line
                    }
                    $envContent = $newContent
                }
                $envContent | Set-Content ".env"

                Write-Host "启动 Docker MySQL 容器..."
                docker-compose up -d mysql
                Write-Host "等待 MySQL 容器启动完成..." -ForegroundColor Yellow
                Start-Sleep 15  # 等待MySQL启动

                # 测试数据库连接
                Write-Host "测试数据库连接..."
                $testConnection = $false
                for ($i = 0; $i -lt 3; $i++) {
                    try {
                        & ".\venv\Scripts\python.exe" -c "
import os
os.environ['DATABASE_URL'] = 'mysql+pymysql://root:123456@localhost:3306/testdb'
from sqlalchemy import create_engine
engine = create_engine(os.environ['DATABASE_URL'])
conn = engine.connect()
conn.close()
print('数据库连接成功')
" 2>$null
                        if ($LASTEXITCODE -eq 0) {
                            $testConnection = $true
                            break
                        }
                    } catch {
                        Write-Host "连接测试失败，重试中..." -ForegroundColor Yellow
                        Start-Sleep 5
                    }
                }

                if ($testConnection) {
                    Write-Host "Docker MySQL 配置成功！" -ForegroundColor Green
                    $dbConnected = $true

                    # 询问是否运行数据库初始化
                    Write-Host "`n数据库连接成功！" -ForegroundColor Green
                    $runInitDb = Read-Host "是否运行数据库初始化脚本 (init_db.py)? 这将删除现有数据并导入示例数据 (y/n)"
                    if ($runInitDb -eq "y" -or $runInitDb -eq "Y") {
                        Write-Host "运行数据库初始化..." -ForegroundColor Cyan
                        try {
                            & ".\venv\Scripts\python.exe" init_db.py
                            if ($LASTEXITCODE -eq 0) {
                                Write-Host "数据库初始化成功！" -ForegroundColor Green
                            } else {
                                Write-Warning "数据库初始化失败，请检查错误信息"
                            }
                        } catch {
                            Write-Warning "运行 init_db.py 时出错: $_"
                        }
                    } else {
                        Write-Host "跳过数据库初始化" -ForegroundColor Yellow
                    }
                } else {
                    Write-Warning "Docker MySQL 启动可能有问题，请检查容器状态"
                    Write-Host "可以运行: docker-compose logs db" -ForegroundColor Yellow
                }
            } else {
                Write-Warning "Docker 未安装或未启动，请手动配置数据库"
            }
        }
        "2" {
            Write-Host "配置本地 MySQL..." -ForegroundColor Cyan

            # 询问MySQL连接信息
            $mysqlHost = Read-Host "MySQL 主机地址 (默认: localhost)"
            if ([string]::IsNullOrWhiteSpace($mysqlHost)) { $mysqlHost = "localhost" }

            $mysqlPort = Read-Host "MySQL 端口 (默认: 3306)"
            if ([string]::IsNullOrWhiteSpace($mysqlPort)) { $mysqlPort = "3306" }

            $mysqlUser = Read-Host "MySQL 用户名 (默认: root)"
            if ([string]::IsNullOrWhiteSpace($mysqlUser)) { $mysqlUser = "root" }

            $mysqlPassword = Read-Host "MySQL 密码" -AsSecureString
            $mysqlPasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($mysqlPassword))

            $mysqlDatabase = Read-Host "数据库名称 (默认: testdb)"
            if ([string]::IsNullOrWhiteSpace($mysqlDatabase)) { $mysqlDatabase = "testdb" }

            # 构建数据库连接字符串
            $databaseUrl = "mysql+pymysql://$mysqlUser`:$mysqlPasswordPlain@$mysqlHost`:$mysqlPort/$mysqlDatabase"

            # 更新.env文件
            Write-Host "更新 .env 文件中的数据库配置..."
            $envContent = Get-Content ".env" | ForEach-Object {
                if ($_ -match "^DATABASE_URL=" -or $_ -match "^#\s*DATABASE_URL=") {
                    "DATABASE_URL=$databaseUrl"
                } else {
                    $_
                }
            }
            $envContent | Set-Content ".env"

            Write-Host "本地 MySQL 配置已更新到 .env 文件" -ForegroundColor Green
            Write-Host "请确保 MySQL 服务正在运行" -ForegroundColor Yellow
            $dbConnected = $true
        }
        "3" {
            Write-Host "配置 SQLite..." -ForegroundColor Cyan
            # 修改.env文件使用SQLite
            $envContent = Get-Content ".env" | ForEach-Object {
                if ($_ -match "^DATABASE_URL=" -or $_ -match "^#\s*DATABASE_URL=") {
                    "DATABASE_URL=sqlite:///inventory_management.db"
                } else {
                    $_
                }
            }
            $envContent | Set-Content ".env"
            Write-Host "SQLite 配置已更新到 .env 文件" -ForegroundColor Green
            $dbConnected = $true
        }
        "4" {
            Write-Host "跳过数据库配置" -ForegroundColor Yellow
        }
        default {
            Write-Warning "无效选择，跳过数据库配置"
        }
    }

    if ($dbConnected) {
        Write-Host "运行数据库迁移..."
        try {
            # 使用虚拟环境中的Python运行迁移
            if (Test-Path "venv\Scripts\python.exe") {
                & ".\venv\Scripts\python.exe" -m flask db upgrade
            } else {
                python -m flask db upgrade
            }

            if ($LASTEXITCODE -eq 0) {
                Write-Host "数据库迁移成功" -ForegroundColor Green
            } else {
                Write-Warning "数据库迁移失败，请检查数据库连接配置"
            }
        } catch {
            Write-Warning "数据库迁移时出错: $_"
            Write-Host "请手动运行: python -m flask db upgrade" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "跳过数据库迁移" -ForegroundColor Yellow
}

Write-Host "`n=== 项目配置完成 ===" -ForegroundColor Green

# 显示配置摘要
Write-Host "`n配置摘要:" -ForegroundColor Cyan
Write-Host "✓ Python 虚拟环境: $(if (Test-Path 'venv') {'已配置'} else {'未配置'})"
Write-Host "✓ Python 依赖: $(if (!$SkipVenv) {'已安装'} else {'跳过'})"
Write-Host "✓ 前端依赖: $(if (!$SkipFrontend -and (Test-Path 'frontend/node_modules')) {'已安装'} else {'跳过或失败'})"
Write-Host "✓ 环境配置: $(if (Test-Path '.env') {'已创建'} else {'未创建'})"
Write-Host "✓ 数据库迁移: $(if (!$SkipMigration) {'已尝试'} else {'跳过'})"

# 显示下一步操作
Write-Host "`n下一步操作:" -ForegroundColor Cyan
Write-Host "1. 编辑 .env 文件，配置正确的数据库连接"
if (!$SkipMigration -eq $false -or $dbConnected -eq $false) {
    Write-Host "2. 如果数据库迁移未成功，请手动运行:"
    Write-Host "   venv\Scripts\python.exe -m flask db upgrade"
}
Write-Host "3. 运行项目启动脚本:"
Write-Host "   .\windows-start.ps1"

# 提供有用的命令
Write-Host "`n常用命令:" -ForegroundColor Cyan
Write-Host "激活虚拟环境: venv\Scripts\Activate.ps1"
Write-Host "运行后端: venv\Scripts\python.exe app.py"
Write-Host "运行前端: cd frontend && npm run dev"
Write-Host "数据库迁移: venv\Scripts\python.exe -m flask db upgrade"

pause