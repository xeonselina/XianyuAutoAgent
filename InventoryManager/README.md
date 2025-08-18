# 库存管理服务 (Inventory Management Service)

一个基于Web的内网库存管理服务，提供甘特图界面、库存查询和API服务。

## 功能特性

### 🎯 核心功能
- **甘特图界面**: 可视化的设备租赁时间管理
- **库存查询**: 实时查询可用设备
- **租赁管理**: 添加、删除、修改租赁记录
- **RESTful API**: 支持其他系统集成

### 📊 甘特图特性
- 纵坐标：设备列表
- 横坐标：时间轴（天为单位）
- 今天标记：垂直红线显示当前日期
- 占用标记：黄色块显示已占用时间
- 交互操作：点击添加/删除租赁记录

### 🔧 技术架构
- **后端**: Python Flask + MySQL
- **前端**: HTML5 + JavaScript + Chart.js
- **数据库**: MySQL 8.0+
- **部署**: Docker + Docker Compose

## 快速开始

### 使用Makefile（推荐）

我们提供了完整的Makefile构建脚本，特别针对ARM Mac开发和x86 Docker部署进行了优化：

```bash
# 查看所有可用命令
make help

# 快速启动开发环境
make dev

# 快速启动Docker环境
make docker-dev

# 查看详细使用说明
# 参考 docs/Makefile使用说明.md
```

### 使用Docker部署（推荐）

1. **克隆项目**
```bash
git clone <repository-url>
cd InventoryManager
```

2. **配置环境变量**
```bash
# 选择对应的环境配置文件
cp env.local .env          # 本地开发环境
# 或者
cp env.production .env     # 生产环境
# 或者
cp env.docker .env         # Docker环境

# 编辑.env文件，根据实际情况修改配置值
nano .env
```

**注意**: 系统提供了多个环境配置文件模板：
- `env.example` - 完整配置参考
- `env.local` - 本地开发环境
- `env.production` - 生产环境
- `env.docker` - Docker环境

详细配置说明请参考 [环境变量配置说明](docs/环境变量配置说明.md)

3. **启动服务**
```bash
docker-compose up -d
```

4. **访问服务**
- Web界面: http://localhost:5000
- API文档: http://localhost:5000/api/docs

### 手动部署

1. **安装依赖**
```bash
pip install -r requirements.txt
```

2. **配置数据库**
```bash
# 创建MySQL数据库
mysql -u root -p
CREATE DATABASE inventory_management;
```

3. **初始化数据库**
```bash
python init_db.py
```

4. **启动服务**
```bash
python app.py
```

## 项目结构

```
InventoryManager/
├── app/                    # 主应用目录
│   ├── __init__.py        # Flask应用初始化
│   ├── models/            # 数据模型
│   ├── routes/            # 路由定义
│   ├── services/          # 业务逻辑
│   └── utils/             # 工具函数
├── static/                 # 静态文件
│   ├── css/               # 样式文件
│   ├── js/                # JavaScript文件
│   └── images/            # 图片资源
├── templates/              # HTML模板
├── migrations/             # 数据库迁移文件
├── tests/                  # 测试文件
├── docker/                 # Docker相关文件
├── requirements.txt        # Python依赖
├── docker-compose.yml      # Docker编排文件
├── Dockerfile             # Docker镜像构建
└── README.md              # 项目说明
```

## API文档

### 库存查询API

#### 查询可用设备
```http
GET /api/inventory/available
```

**参数:**
- `start_date`: 开始日期 (YYYY-MM-DD)
- `end_date`: 结束日期 (YYYY-MM-DD)
- `device_type`: 设备类型 (可选)

**响应:**
```json
{
  "success": true,
  "data": [
    {
      "device_id": "DEVICE001",
      "device_name": "iPhone 15 Pro",
      "device_type": "手机",
      "status": "available"
    }
  ]
}
```

#### 添加租赁记录
```http
POST /api/rentals
```

**请求体:**
```json
{
  "device_id": "DEVICE001",
  "start_date": "2024-01-15",
  "end_date": "2024-01-17",
  "customer_name": "张三",
  "purpose": "测试使用"
}
```

#### 删除租赁记录
```http
DELETE /api/rentals/{rental_id}
```

### 设备管理API

#### 获取设备列表
```http
GET /api/devices
```

#### 添加设备
```http
POST /api/devices
```

#### 更新设备信息
```http
PUT /api/devices/{device_id}
```

## 数据库设计

### 主要表结构

#### 设备表 (devices)
```sql
CREATE TABLE devices (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    type VARCHAR(50) NOT NULL,
    model VARCHAR(100),
    status ENUM('available', 'maintenance', 'retired') DEFAULT 'available',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

#### 租赁记录表 (rentals)
```sql
CREATE TABLE rentals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(50) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    customer_name VARCHAR(100) NOT NULL,
    purpose TEXT,
    status ENUM('active', 'completed', 'cancelled') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES devices(id)
);
```

## 开发指南

### 环境要求
- Python 3.8+
- MySQL 8.0+
- Node.js 14+ (可选，用于前端开发)

### 开发模式启动
```bash
# 设置开发环境变量
export FLASK_ENV=development
export FLASK_DEBUG=1

# 启动服务
python app.py
```

### 运行测试
```bash
# 运行所有测试
python -m pytest tests/

# 运行特定测试
python -m pytest tests/test_inventory.py -v

# 生成覆盖率报告
python -m pytest tests/ --cov=app --cov-report=html
```

## 部署说明

### 生产环境配置
1. 修改`.env`文件中的生产环境配置
2. 设置适当的数据库连接池大小
3. 配置日志级别和输出
4. 设置反向代理（如Nginx）

### 监控和日志
- 应用日志: `/var/log/inventory_service/app.log`
- 访问日志: `/var/log/inventory_service/access.log`
- 健康检查: `/health` 端点

## 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 联系方式

- 项目维护者: [Your Name]
- 邮箱: [your.email@example.com]
- 项目链接: [https://github.com/username/inventory-management]
