# InventoryManager Windows 项目启动脚本
# 启动数据库、后端服务和前端应用

param(
    [switch]$Production,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$SkipDatabase,
    [switch]$Help
)

if ($Help) {
    Write-Host "InventoryManager Windows 项目启动脚本" -ForegroundColor Green
    Write-Host "参数说明:"
    Write-Host "  -Production     生产模式启动"
    Write-Host "  -BackendOnly    仅启动后端服务"
    Write-Host "  -FrontendOnly   仅启动前端服务"
    Write-Host "  -SkipDatabase   跳过数据库启动"
    Write-Host "  -Help           显示帮助信息"
    Write-Host ""
    Write-Host "使用示例:"
    Write-Host "  .\windows-start.ps1                    # 开发模式完整启动"
    Write-Host "  .\windows-start.ps1 -Production        # 生产模式启动"
    Write-Host "  .\windows-start.ps1 -BackendOnly       # 仅启动后端"
    exit
}

Write-Host "=== InventoryManager 项目启动脚本 ===" -ForegroundColor Green

# 检查是否在项目目录
if (!(Test-Path "app.py" -PathType Leaf)) {
    Write-Error "请在 InventoryManager 项目根目录中运行此脚本！"
    Write-Host "当前目录: $(Get-Location)" -ForegroundColor Red
    pause
    exit 1
}

# 检查虚拟环境是否存在
if (!(Test-Path "venv\Scripts\python.exe")) {
    Write-Error "Python 虚拟环境不存在！请先运行 windows-config.ps1"
    pause
    exit 1
}

# 检查.env文件是否存在
if (!(Test-Path ".env")) {
    Write-Error ".env 配置文件不存在！请先运行 windows-config.ps1"
    pause
    exit 1
}

$mode = if ($Production) { "生产" } else { "开发" }
Write-Host "启动模式: $mode 模式" -ForegroundColor Cyan

# 创建作业列表来跟踪启动的服务
$global:jobs = @()

# 清理函数
function Cleanup {
    Write-Host "`n正在停止所有服务..." -ForegroundColor Yellow

    # 停止所有后台作业
    foreach ($job in $global:jobs) {
        if ($job -and $job.State -eq "Running") {
            Write-Host "停止服务: $($job.Name)"
            Stop-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -ErrorAction SilentlyContinue
        }
    }

    # 停止可能运行的进程
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*app.py*"} | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -like "*vite*"} | Stop-Process -Force -ErrorAction SilentlyContinue

    Write-Host "服务已停止" -ForegroundColor Green
}

# 设置Ctrl+C处理
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup }

# 启动数据库服务
if (!$SkipDatabase -and !$FrontendOnly) {
    Write-Host "`n启动数据库服务..." -ForegroundColor Cyan

    # 检查Docker是否可用
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            $dockerStatus = docker info 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "启动 Docker MySQL 容器..."
                docker-compose up -d mysql

                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Docker MySQL 启动成功" -ForegroundColor Green
                    Start-Sleep 5  # 等待MySQL完全启动
                } else {
                    Write-Warning "Docker MySQL 启动失败，请检查docker-compose.yml配置"
                }
            } else {
                Write-Warning "Docker 未运行，请手动启动数据库服务"
            }
        } catch {
            Write-Warning "无法连接到 Docker，请确保 Docker Desktop 正在运行"
        }
    } else {
        Write-Warning "Docker 未安装，请确保数据库服务正在运行"
    }
}

# 启动后端服务
if (!$FrontendOnly) {
    Write-Host "`n启动后端服务..." -ForegroundColor Cyan

    # 激活虚拟环境并启动后端
    $backendScript = {
        param($ProjectPath, $IsProduction)

        Set-Location $ProjectPath

        # 激活虚拟环境
        & ".\venv\Scripts\Activate.ps1"

        # 设置环境变量
        if ($IsProduction) {
            $env:FLASK_ENV = "production"
        } else {
            $env:FLASK_ENV = "development"
        }

        # 启动Flask应用
        Write-Host "正在启动后端服务..." -ForegroundColor Green
        & ".\venv\Scripts\python.exe" app.py
    }

    $backendJob = Start-Job -ScriptBlock $backendScript -ArgumentList (Get-Location).Path, $Production -Name "Backend"
    $global:jobs += $backendJob

    # 等待后端启动
    Write-Host "等待后端服务启动..." -ForegroundColor Yellow
    Start-Sleep 3

    # 检查后端是否启动成功
    $backendRunning = $false
    for ($i = 0; $i -lt 10; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://localhost:5001/api/health" -Method GET -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($response.StatusCode -eq 200) {
                $backendRunning = $true
                break
            }
        } catch {
            Start-Sleep 2
        }
    }

    if ($backendRunning) {
        Write-Host "后端服务启动成功 - http://localhost:5001" -ForegroundColor Green
    } else {
        Write-Warning "后端服务可能启动失败，请检查日志"
        # 显示后端输出
        Receive-Job $backendJob -ErrorAction SilentlyContinue | Write-Host
    }
}

# 启动前端服务
if (!$BackendOnly) {
    Write-Host "`n配置前端服务..." -ForegroundColor Cyan

    if (Test-Path "frontend" -PathType Container) {
        if ($Production) {
            # 生产模式：构建前端并使用后端服务静态文件
            Write-Host "构建前端生产版本..."
            Push-Location frontend
            try {
                npm run build
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "前端构建成功" -ForegroundColor Green
                    Write-Host "前端将通过后端服务提供 - http://localhost:5001" -ForegroundColor Green
                } else {
                    Write-Error "前端构建失败"
                }
            } catch {
                Write-Error "前端构建时出错: $_"
            } finally {
                Pop-Location
            }
        } else {
            # 开发模式：启动前端开发服务器
            Write-Host "启动前端开发服务器..."

            $frontendScript = {
                param($ProjectPath)

                Set-Location "$ProjectPath\frontend"

                # 启动Vite开发服务器
                Write-Host "正在启动前端开发服务器..." -ForegroundColor Green
                npm run dev
            }

            $frontendJob = Start-Job -ScriptBlock $frontendScript -ArgumentList (Get-Location).Path -Name "Frontend"
            $global:jobs += $frontendJob

            # 等待前端启动
            Write-Host "等待前端服务启动..." -ForegroundColor Yellow
            Start-Sleep 5

            # 检查前端是否启动成功
            $frontendRunning = $false
            for ($i = 0; $i -lt 10; $i++) {
                try {
                    $response = Invoke-WebRequest -Uri "http://localhost:5173" -Method GET -TimeoutSec 2 -ErrorAction SilentlyContinue
                    if ($response.StatusCode -eq 200) {
                        $frontendRunning = $true
                        break
                    }
                } catch {
                    Start-Sleep 2
                }
            }

            if ($frontendRunning) {
                Write-Host "前端开发服务器启动成功 - http://localhost:5173" -ForegroundColor Green
            } else {
                Write-Warning "前端服务器可能启动失败，请检查日志"
                # 显示前端输出
                Receive-Job $frontendJob -ErrorAction SilentlyContinue | Write-Host
            }
        }
    } else {
        Write-Warning "frontend 目录不存在，跳过前端启动"
    }
}

# 显示服务状态
Write-Host "`n=== 服务启动完成 ===" -ForegroundColor Green

$services = @()
if (!$FrontendOnly) {
    $services += "后端服务: http://localhost:5001"
    $services += "API文档: http://localhost:5001/api/docs"
}

if (!$BackendOnly) {
    if ($Production) {
        $services += "前端应用: http://localhost:5001 (通过后端服务)"
    } else {
        $services += "前端应用: http://localhost:5173"
    }
}

Write-Host "`n可访问的服务:" -ForegroundColor Cyan
foreach ($service in $services) {
    Write-Host "  • $service" -ForegroundColor White
}

# 显示有用信息
Write-Host "`n有用信息:" -ForegroundColor Cyan
Write-Host "  • 按 Ctrl+C 停止所有服务"
Write-Host "  • 后端日志文件: logs/inventory_service.log"
Write-Host "  • 数据库管理: 可使用任何MySQL客户端连接"

if ($global:jobs.Count -gt 0) {
    Write-Host "  • 查看服务输出: Receive-Job <JobName>"
    Write-Host "  • 当前运行的作业:"
    foreach ($job in $global:jobs) {
        if ($job.State -eq "Running") {
            Write-Host "    - $($job.Name): $($job.State)" -ForegroundColor Green
        } else {
            Write-Host "    - $($job.Name): $($job.State)" -ForegroundColor Red
        }
    }
}

# 持续监控服务状态
Write-Host "`n服务监控中..." -ForegroundColor Yellow
Write-Host "按任意键退出并停止所有服务" -ForegroundColor Yellow

try {
    # 持续显示作业状态
    do {
        Start-Sleep 5

        # 检查作业状态
        $runningJobs = 0
        foreach ($job in $global:jobs) {
            if ($job.State -eq "Running") {
                $runningJobs++
            } elseif ($job.State -eq "Failed" -or $job.State -eq "Stopped") {
                Write-Host "警告: 服务 $($job.Name) 已停止" -ForegroundColor Red
                # 显示错误输出
                $jobOutput = Receive-Job $job -ErrorAction SilentlyContinue
                if ($jobOutput) {
                    Write-Host "错误信息: $jobOutput" -ForegroundColor Red
                }
            }
        }

        # 如果没有运行的作业，退出
        if ($runningJobs -eq 0 -and $global:jobs.Count -gt 0) {
            Write-Host "所有服务已停止" -ForegroundColor Red
            break
        }

        # 检查是否有按键输入
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            break
        }

    } while ($true)
} finally {
    Cleanup
}

Write-Host "`n项目已停止" -ForegroundColor Green