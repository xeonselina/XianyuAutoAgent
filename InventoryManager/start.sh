#!/bin/bash

# 库存管理服务启动脚本

echo "=== 库存管理服务启动脚本 ==="

# 检查Python版本
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
if [[ $(echo "$python_version >= 3.8" | bc -l) -eq 0 ]]; then
    echo "错误: 需要Python 3.8或更高版本，当前版本: $python_version"
    exit 1
fi

echo "Python版本检查通过: $python_version"

# 检查虚拟环境
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "警告: 未检测到虚拟环境，建议使用虚拟环境"
    read -p "是否继续？(y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "虚拟环境: $VIRTUAL_ENV"
fi

# 安装依赖
echo "安装Python依赖..."
pip install -r requirements.txt

# 检查环境变量文件
if [[ ! -f ".env" ]]; then
    echo "创建环境变量文件..."
    cat > .env << EOF
# 应用配置
FLASK_ENV=development
SECRET_KEY=dev-secret-key-change-in-production
API_KEY=dev-api-key-change-in-production

# 数据库配置
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/inventory_management

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/inventory_service.log

# 跨域配置
CORS_ORIGINS=http://localhost:3000,http://localhost:8080

# 业务配置
DEFAULT_RENTAL_DAYS=7
MAX_RENTAL_DAYS=30
MIN_ADVANCE_BOOKING_DAYS=1

# 时区配置
TIMEZONE=Asia/Shanghai
EOF
    echo "环境变量文件已创建，请根据实际情况修改 .env 文件"
fi

# 创建必要的目录
echo "创建必要的目录..."
mkdir -p logs
mkdir -p uploads
mkdir -p migrations

# 检查数据库连接
echo "检查数据库连接..."
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()

try:
    import pymysql
    from urllib.parse import urlparse
    
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        parsed = urlparse(db_url)
        conn = pymysql.connect(
            host=parsed.hostname or 'localhost',
            port=parsed.port or 3306,
            user=parsed.username or 'root',
            password=parsed.password or 'password',
            database=parsed.path.lstrip('/') or 'inventory_management'
        )
        conn.close()
        print('数据库连接成功')
    else:
        print('警告: 未设置DATABASE_URL环境变量')
except Exception as e:
    print(f'数据库连接失败: {e}')
    print('请检查数据库配置并确保MySQL服务正在运行')
"

# 初始化数据库
echo "初始化数据库..."
python3 -m flask init-db

# 填充示例数据
echo "填充示例数据..."
python3 -m flask seed-data

echo "=== 启动服务 ==="
echo "Web界面: http://localhost:5000"
echo "API文档: http://localhost:5000/api/docs"
echo "健康检查: http://localhost:5000/health"
echo ""
echo "按 Ctrl+C 停止服务"

# 启动应用
python3 app.py
