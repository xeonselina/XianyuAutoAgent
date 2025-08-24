# 库存管理服务 Docker 部署指南

本指南介绍如何在 x86 服务器上使用 Docker 部署库存管理服务。

## 📋 系统要求

- **操作系统**: Linux (推荐 Ubuntu 20.04+ 或 CentOS 8+)
- **架构**: x86_64
- **内存**: 至少 2GB RAM
- **硬盘**: 至少 10GB 可用空间
- **Docker**: 20.10+
- **Docker Compose**: 2.0+

## 🚀 快速部署

### 1. 安装 Docker 和 Docker Compose

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 安装 Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# 重新登录以应用用户组更改
logout
```

### 2. 克隆项目并配置环境

```bash
git clone <repository-url>
cd XianyuAutoAgent/InventoryManager

# 复制环境变量模板
cp .env.example .env

# 编辑环境变量文件
vim .env
```

### 3. 配置环境变量

编辑 `.env` 文件，设置以下关键配置：

```bash
# 基础配置
SECRET_KEY=your-super-secret-key-change-this-in-production
FLASK_ENV=production

# 顺丰快递API (必须配置)
SF_PARTNER_ID=your-sf-partner-id
SF_CHECKWORD=your-sf-checkword
SF_TEST_MODE=false

# 阿里云OCR (可选)
ALIBABA_CLOUD_ACCESS_KEY_ID=your-access-key-id
ALIBABA_CLOUD_ACCESS_KEY_SECRET=your-access-key-secret
```

### 4. 一键部署

```bash
# 使用部署脚本
./deploy.sh

# 或者手动部署
docker-compose up -d
```

## 📁 目录结构

```
InventoryManager/
├── Dockerfile              # 应用容器配置
├── docker-compose.yml      # 服务编排配置
├── .dockerignore           # Docker忽略文件
├── deploy.sh              # 一键部署脚本
├── init.sql               # 数据库初始化脚本
├── docker/
│   └── nginx/
│       └── nginx.conf     # Nginx配置文件
└── .env                   # 环境变量配置
```

## 🐳 服务组件

### 核心服务

| 服务 | 容器名 | 端口 | 描述 |
|------|--------|------|------|
| app | inventory_app | 5001 | 库存管理应用 |
| mysql | inventory_mysql | 3306 | MySQL 8.0 数据库 |
| redis | inventory_redis | 6379 | Redis 缓存 |
| nginx | inventory_nginx | 80/443 | 反向代理 (可选) |

### 数据卷

| 卷名 | 用途 |
|------|------|
| mysql_data | MySQL 数据持久化 |
| redis_data | Redis 数据持久化 |
| app_logs | 应用日志 |
| app_uploads | 文件上传存储 |

## 🔧 管理命令

### 使用部署脚本

```bash
# 部署服务
./deploy.sh deploy

# 停止服务
./deploy.sh stop

# 重启服务
./deploy.sh restart

# 查看日志
./deploy.sh logs

# 查看状态
./deploy.sh status

# 清理所有数据
./deploy.sh clean
```

### 使用 Docker Compose

```bash
# 启动所有服务
docker-compose up -d

# 停止所有服务
docker-compose down

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f app

# 重启特定服务
docker-compose restart app

# 构建并启动
docker-compose up --build -d
```

## 🔍 监控和调试

### 健康检查

```bash
# 检查应用健康状态
curl http://localhost:5001/

# 检查数据库连接
docker-compose exec mysql mysqladmin ping -h localhost -u root -prootpassword

# 检查 Redis
docker-compose exec redis redis-cli ping
```

### 查看日志

```bash
# 应用日志
docker-compose logs -f app

# 数据库日志
docker-compose logs -f mysql

# 所有服务日志
docker-compose logs -f
```

### 进入容器

```bash
# 进入应用容器
docker-compose exec app bash

# 进入数据库容器
docker-compose exec mysql bash

# 进入 Redis 容器
docker-compose exec redis sh
```

## 🛠 故障排除

### 常见问题

1. **容器启动失败**
   ```bash
   # 查看详细错误
   docker-compose logs app
   
   # 检查配置文件
   docker-compose config
   ```

2. **数据库连接失败**
   ```bash
   # 确保 MySQL 容器正常运行
   docker-compose ps mysql
   
   # 检查数据库日志
   docker-compose logs mysql
   ```

3. **端口冲突**
   ```bash
   # 修改 docker-compose.yml 中的端口映射
   ports:
     - "5002:5001"  # 改为其他端口
   ```

4. **磁盘空间不足**
   ```bash
   # 清理未使用的镜像和容器
   docker system prune -af
   
   # 查看磁盘使用情况
   docker system df
   ```

### 性能优化

1. **调整 Gunicorn 配置**
   
   修改 `Dockerfile` 中的启动参数：
   ```bash
   # 根据服务器配置调整 workers 数量
   CMD ["gunicorn", "--workers", "8", ...]
   ```

2. **MySQL 性能调优**
   
   在 `docker-compose.yml` 中添加：
   ```yaml
   mysql:
     command: --innodb-buffer-pool-size=1G --max-connections=200
   ```

3. **启用 Nginx 缓存**
   
   修改 `nginx.conf` 添加缓存配置。

## 🔐 安全配置

### 生产环境建议

1. **更改默认密码**
   ```bash
   # 修改 .env 文件中的数据库密码
   MYSQL_ROOT_PASSWORD=complex-password-here
   ```

2. **使用 HTTPS**
   ```bash
   # 将 SSL 证书放入 docker/nginx/ssl/
   # 启用 nginx.conf 中的 HTTPS 配置
   ```

3. **限制网络访问**
   ```bash
   # 修改端口映射，仅绑定本地
   ports:
     - "127.0.0.1:5001:5001"
   ```

4. **定期备份**
   ```bash
   # 数据库备份
   docker-compose exec mysql mysqldump -u root -prootpassword inventory_db > backup.sql
   
   # 备份数据卷
   docker run --rm -v inventory_mysql_data:/data -v $(pwd):/backup alpine tar czf /backup/mysql_backup.tar.gz -C /data .
   ```

## 📈 扩展部署

### 水平扩展

```yaml
# docker-compose.yml
services:
  app:
    deploy:
      replicas: 3  # 启动3个应用实例
    
  nginx:
    # 配置负载均衡
```

### 使用外部数据库

```yaml
# 使用外部 MySQL
services:
  app:
    environment:
      - DATABASE_URL=mysql+pymysql://user:pass@external-mysql:3306/db
```

## 📞 技术支持

- 查看应用日志: `docker-compose logs -f app`
- 健康检查: `curl http://localhost:5001/`
- 容器状态: `docker-compose ps`
- 资源使用: `docker stats`

部署完成后，访问 http://localhost:5001 即可使用库存管理系统。