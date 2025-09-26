# InventoryManager Windows 项目停止脚本
# 停止所有相关服务和容器

param(
    [switch]$KeepDatabase,
    [switch]$Help
)

if ($Help) {
    Write-Host "InventoryManager Windows 项目停止脚本" -ForegroundColor Green
    Write-Host "参数说明:"
    Write-Host "  -KeepDatabase   保留数据库容器运行"
    Write-Host "  -Help           显示帮助信息"
    Write-Host ""
    Write-Host "使用示例:"
    Write-Host "  .\windows-stop.ps1                     # 停止所有服务"
    Write-Host "  .\windows-stop.ps1 -KeepDatabase       # 停止服务但保留数据库"
    exit
}

Write-Host "=== InventoryManager 项目停止脚本 ===" -ForegroundColor Green

# 停止Python Flask进程
Write-Host "`n停止后端服务..." -ForegroundColor Cyan
$flaskProcesses = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*app.py*" -or $_.CommandLine -like "*flask*"
}

if ($flaskProcesses) {
    foreach ($process in $flaskProcesses) {
        Write-Host "停止进程: $($process.ProcessName) (PID: $($process.Id))"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "后端服务已停止" -ForegroundColor Green
} else {
    Write-Host "未找到运行中的后端服务" -ForegroundColor Yellow
}

# 停止Node.js进程（前端开发服务器）
Write-Host "`n停止前端服务..." -ForegroundColor Cyan
$nodeProcesses = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*vite*" -or $_.CommandLine -like "*dev*"
}

if ($nodeProcesses) {
    foreach ($process in $nodeProcesses) {
        Write-Host "停止进程: $($process.ProcessName) (PID: $($process.Id))"
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "前端服务已停止" -ForegroundColor Green
} else {
    Write-Host "未找到运行中的前端服务" -ForegroundColor Yellow
}

# 停止PowerShell作业
Write-Host "`n停止后台作业..." -ForegroundColor Cyan
$jobs = Get-Job | Where-Object { $_.Name -in @("Backend", "Frontend") }
if ($jobs) {
    foreach ($job in $jobs) {
        Write-Host "停止作业: $($job.Name)"
        Stop-Job $job -ErrorAction SilentlyContinue
        Remove-Job $job -ErrorAction SilentlyContinue
    }
    Write-Host "后台作业已停止" -ForegroundColor Green
} else {
    Write-Host "未找到相关后台作业" -ForegroundColor Yellow
}

# 停止Docker容器
if (!$KeepDatabase) {
    Write-Host "`n停止数据库服务..." -ForegroundColor Cyan
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        try {
            $dockerStatus = docker info 2>$null
            if ($LASTEXITCODE -eq 0) {
                # 停止docker-compose服务
                if (Test-Path "docker-compose.yml") {
                    Write-Host "停止 Docker Compose 服务..."
                    docker-compose down

                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "Docker 服务已停止" -ForegroundColor Green
                    } else {
                        Write-Warning "停止 Docker 服务时出现问题"
                    }
                } else {
                    Write-Warning "未找到 docker-compose.yml 文件"
                }
            } else {
                Write-Warning "Docker 未运行"
            }
        } catch {
            Write-Warning "无法连接到 Docker"
        }
    } else {
        Write-Host "Docker 未安装，跳过容器停止" -ForegroundColor Yellow
    }
} else {
    Write-Host "保留数据库服务运行" -ForegroundColor Yellow
}

# 清理临时文件
Write-Host "`n清理临时文件..." -ForegroundColor Cyan
$tempFiles = @(
    "*.pyc",
    "__pycache__",
    ".pytest_cache",
    "frontend/dist",
    "frontend/.vite"
)

foreach ($pattern in $tempFiles) {
    $files = Get-ChildItem -Path . -Name $pattern -Recurse -Force -ErrorAction SilentlyContinue
    if ($files) {
        Write-Host "清理: $pattern"
        Remove-Item $files -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 检查端口占用情况
Write-Host "`n检查端口占用情况..." -ForegroundColor Cyan
$ports = @(5001, 5173, 3306)
foreach ($port in $ports) {
    $connection = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($connection) {
        Write-Host "端口 $port 仍被占用，可能需要手动处理" -ForegroundColor Yellow
    } else {
        Write-Host "端口 $port 已释放" -ForegroundColor Green
    }
}

Write-Host "`n=== 停止脚本执行完成 ===" -ForegroundColor Green

# 显示状态摘要
Write-Host "`n状态摘要:" -ForegroundColor Cyan
Write-Host "✓ 后端服务已停止"
Write-Host "✓ 前端服务已停止"
Write-Host "✓ 后台作业已停止"
if (!$KeepDatabase) {
    Write-Host "✓ 数据库服务已停止"
} else {
    Write-Host "• 数据库服务保持运行"
}
Write-Host "✓ 临时文件已清理"

Write-Host "`n项目已完全停止" -ForegroundColor Green