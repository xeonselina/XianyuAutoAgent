#!/bin/bash
# 设备状态定时任务启动脚本

# 加载 .env 文件
if [ -f .env ]; then
    echo "📁 加载 .env 文件..."
    export $(cat .env | grep -v '^#' | xargs)
    echo "✅ 环境变量已加载"
else
    echo "⚠️  未找到 .env 文件，使用默认配置"
    # 设置默认环境变量
    export DATABASE_URL="mysql+pymysql://root:123456@localhost:3306/testdb"
    export APP_PORT="5001"
fi

# 从环境变量解析数据库连接信息
parse_database_url() {
    local url="$DATABASE_URL"
    if [[ $url =~ mysql\+pymysql://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+) ]]; then
        DB_USER="${BASH_REMATCH[1]}"
        DB_PASS="${BASH_REMATCH[2]}"
        DB_HOST="${BASH_REMATCH[3]}"
        DB_PORT="${BASH_REMATCH[4]}"
        DB_NAME="${BASH_REMATCH[5]}"
    else
        echo "❌ 无法解析数据库URL: $url"
        exit 1
    fi
}

# 解析数据库连接信息
parse_database_url

echo "🔍 数据库连接信息:"
echo "  主机: $DB_HOST"
echo "  端口: $DB_PORT"
echo "  用户: $DB_USER"
echo "  数据库: $DB_NAME"

# 检查MySQL容器是否运行
echo "检查MySQL容器状态..."
if ! docker ps | grep -q mysql; then
    echo "❌ MySQL容器未运行，请启动MySQL容器"
    echo "启动MySQL: docker start mysql-local"
    exit 1
fi

echo "✅ MySQL容器正在运行"

# 使用Docker检查MySQL连接
echo "检查MySQL连接..."
if ! docker exec mysql-local mysql -u "$DB_USER" -p"$DB_PASS" -e "SELECT 1;" > /dev/null 2>&1; then
    echo "❌ MySQL连接失败，请检查用户名和密码"
    exit 1
fi

echo "✅ MySQL连接成功"

# 检查数据库是否存在
if ! docker exec mysql-local mysql -u "$DB_USER" -p"$DB_PASS" -e "USE $DB_NAME;" > /dev/null 2>&1; then
    echo "❌ 数据库 $DB_NAME 不存在，请先初始化数据库"
    echo "初始化数据库: make db-init"
    exit 1
fi

echo "✅ 数据库 $DB_NAME 存在"

# 启动定时任务
echo "启动设备状态自动更新定时任务..."
python3 device_status_scheduler.py
