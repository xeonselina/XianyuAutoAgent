#!/bin/bash

# 库存管理服务部署脚本
# 适用于x86服务器部署

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查Docker和Docker Compose
check_dependencies() {
    print_info "检查依赖..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        print_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi
    
    print_info "依赖检查通过"
}

# 检查环境变量文件
check_env_file() {
    print_info "检查环境变量配置..."
    
    if [ ! -f ".env" ]; then
        print_warn ".env 文件不存在，从 .env.example 创建"
        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_warn "请编辑 .env 文件，配置必要的环境变量"
            print_warn "特别是数据库密码、顺丰API密钥等敏感信息"
        else
            print_error ".env.example 文件不存在，请手动创建 .env 文件"
            exit 1
        fi
    else
        print_info "环境变量文件存在"
    fi
}

# 创建必要的目录
create_directories() {
    print_info "创建必要的目录..."
    
    mkdir -p logs
    mkdir -p uploads
    mkdir -p docker/nginx/ssl
    
    # 设置权限
    chmod 755 logs uploads
    
    print_info "目录创建完成"
}

# 构建和启动服务
build_and_start() {
    print_info "构建和启动服务..."
    
    # 停止已存在的服务
    print_info "停止已存在的服务..."
    docker-compose down --remove-orphans || true
    
    # 构建镜像
    print_info "构建应用镜像..."
    docker-compose build --no-cache app
    
    # 启动服务
    print_info "启动服务..."
    docker-compose up -d
    
    # 等待服务启动
    print_info "等待服务启动..."
    sleep 30
    
    # 检查服务状态
    print_info "检查服务状态..."
    docker-compose ps
    
    # 检查应用健康状态
    print_info "检查应用健康状态..."
    for i in {1..10}; do
        if curl -f http://localhost:5001/ >/dev/null 2>&1; then
            print_info "应用启动成功！"
            break
        else
            print_warn "第 $i 次健康检查失败，等待..."
            sleep 10
        fi
        
        if [ $i -eq 10 ]; then
            print_error "应用启动失败，请检查日志"
            docker-compose logs app
            exit 1
        fi
    done
}

# 初始化数据库
init_database() {
    print_info "初始化数据库..."
    
    # 等待MySQL启动
    print_info "等待MySQL启动..."
    for i in {1..30}; do
        if docker-compose exec -T mysql mysqladmin ping -h localhost -u root -prootpassword >/dev/null 2>&1; then
            print_info "MySQL 已启动"
            break
        else
            print_warn "等待MySQL启动... ($i/30)"
            sleep 5
        fi
        
        if [ $i -eq 30 ]; then
            print_error "MySQL启动超时"
            docker-compose logs mysql
            exit 1
        fi
    done
    
    # 运行数据库迁移
    print_info "运行数据库迁移..."
    docker-compose exec app python -c "
from app import create_app, db
app = create_app()
with app.app_context():
    db.create_all()
    print('数据库表创建完成')
" || true
    
    print_info "数据库初始化完成"
}

# 显示部署信息
show_deployment_info() {
    print_info "=== 部署完成 ==="
    echo
    echo "服务访问地址："
    echo "  应用服务: http://localhost:5001"
    echo "  Nginx代理: http://localhost (如果启用)"
    echo "  MySQL数据库: localhost:3306"
    echo "  Redis缓存: localhost:6379"
    echo
    echo "管理命令："
    echo "  查看日志: docker-compose logs -f"
    echo "  停止服务: docker-compose down"
    echo "  重启服务: docker-compose restart"
    echo "  查看状态: docker-compose ps"
    echo
    echo "数据持久化："
    echo "  MySQL数据: Docker卷 mysql_data"
    echo "  Redis数据: Docker卷 redis_data"
    echo "  应用日志: Docker卷 app_logs"
    echo "  上传文件: Docker卷 app_uploads"
    echo
    print_info "部署成功！"
}

# 清理函数
cleanup_on_error() {
    print_error "部署失败，正在清理..."
    docker-compose down --remove-orphans || true
    exit 1
}

# 设置错误处理
trap cleanup_on_error ERR

# 主流程
main() {
    print_info "开始部署库存管理服务..."
    
    check_dependencies
    check_env_file
    create_directories
    build_and_start
    init_database
    show_deployment_info
}

# 解析命令行参数
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "stop")
        print_info "停止服务..."
        docker-compose down
        print_info "服务已停止"
        ;;
    "restart")
        print_info "重启服务..."
        docker-compose restart
        print_info "服务已重启"
        ;;
    "logs")
        docker-compose logs -f "${2:-}"
        ;;
    "status")
        docker-compose ps
        ;;
    "clean")
        print_warn "这将删除所有容器、镜像和数据卷！"
        read -p "确认继续？(y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker-compose down -v --rmi all --remove-orphans
            docker system prune -f
            print_info "清理完成"
        else
            print_info "已取消"
        fi
        ;;
    "help")
        echo "用法: $0 [命令]"
        echo
        echo "命令："
        echo "  deploy   部署服务（默认）"
        echo "  stop     停止服务"
        echo "  restart  重启服务"
        echo "  logs     查看日志"
        echo "  status   查看状态"
        echo "  clean    清理所有数据"
        echo "  help     显示帮助"
        ;;
    *)
        print_error "未知命令: $1"
        print_info "使用 '$0 help' 查看帮助"
        exit 1
        ;;
esac