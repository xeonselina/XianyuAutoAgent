# 库存管理服务 (Inventory Management Service)

一个基于Web的内网库存管理服务，提供甘特图界面、库存查询和API服务。

## 功能特性

### 🎯 核心功能
- **甘特图界面**: 可视化的设备租赁时间管理
- **库存查询**: 实时查询可用设备和附件
- **租赁管理**: 添加、删除、修改租赁记录，支持主设备和附件关联
- **设备管理**: 设备和设备型号管理
- **附件管理**: 支持手柄、支架等附件的独立管理
- **合同生成**: 自动生成租赁合同和出货单PDF
- **统计报表**: 租赁统计数据和报表
- **定时任务**: 自动计算统计数据
- **审计日志**: 操作记录追踪
- **RESTful API**: 支持其他系统集成

### 📊 甘特图特性
- 纵坐标：设备列表（支持主设备和附件）
- 横坐标：时间轴（天为单位）
- 今天标记：垂直红线显示当前日期
- 占用标记：彩色块显示已占用时间，不同状态不同颜色
- 交互操作：点击添加/删除租赁记录，支持拖拽调整时间
- 时间导航：快速跳转到今天、下周、下月
- 设备过滤：按设备型号、状态筛选
- 附件显示：关联显示主设备和附件的租赁情况

### 🔧 技术架构

#### 后端技术栈
- **框架**: Flask 3.x
- **ORM**: SQLAlchemy 2.x
- **数据库迁移**: Flask-Migrate (Alembic)
- **数据库**: MySQL 8.0+
- **定时任务**: APScheduler
- **PDF生成**: Playwright
- **HTTP客户端**: Requests

#### 前端技术栈
- **框架**: Vue 3 (Composition API)
- **语言**: TypeScript 5.x
- **构建工具**: Vite 5.x
- **UI框架**: Element Plus
- **状态管理**: Pinia
- **路由**: Vue Router 4
- **HTTP客户端**: Axios
- **图标**: @element-plus/icons-vue

#### 部署
- **容器化**: Docker + Docker Compose
- **构建工具**: Makefile
- **多架构支持**: ARM64 / AMD64

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
│   │   ├── device.py              # 设备模型
│   │   ├── device_model.py        # 设备型号模型
│   │   ├── rental.py              # 租赁记录模型
│   │   ├── audit_log.py           # 审计日志模型
│   │   └── rental_statistics.py   # 租赁统计模型
│   ├── routes/            # 路由定义
│   │   ├── device_api.py          # 设备API路由
│   │   ├── device_model_api.py    # 设备型号API路由
│   │   ├── rental_api.py          # 租赁API路由
│   │   ├── gantt_api.py           # 甘特图API路由
│   │   └── statistics_api.py      # 统计API路由
│   ├── services/          # 业务逻辑
│   │   ├── scheduler.py           # 定时任务服务
│   │   └── statistics_service.py  # 统计服务
│   └── utils/             # 工具函数
│       └── pdf_generator.py       # PDF生成工具
├── frontend/              # 前端项目（Vue 3）
│   ├── src/
│   │   ├── components/    # Vue组件
│   │   ├── views/         # 页面视图
│   │   ├── stores/        # Pinia状态管理
│   │   ├── router/        # 路由配置
│   │   └── utils/         # 工具函数
│   ├── package.json       # 前端依赖
│   └── vite.config.ts     # Vite配置
├── templates/             # HTML模板（PDF模板）
│   ├── rental_contract2.html    # 租赁合同模板
│   └── shipping_order2.html     # 出货单模板
├── migrations/            # 数据库迁移文件
├── scripts/               # 脚本文件
│   ├── export_db_data.py        # 数据库导出脚本
│   └── cron_calculate_statistics.sh  # 统计计算定时脚本
├── docs/                  # 文档目录
├── requirements.txt       # Python依赖
├── docker-compose.yml     # Docker编排文件
├── Dockerfile            # Docker镜像构建
├── Makefile              # 构建脚本
├── init_db.py            # 数据库初始化脚本
└── README.md             # 项目说明
```

## API文档

详细的API文档可以访问：http://localhost:5000/api/docs

### 核心API端点

#### 1. 库存查询API

##### 查询可用设备
```http
GET /api/inventory/available?start_date=2025-01-01&end_date=2025-01-07
```

**响应:**
```json
{
  "success": true,
  "available_devices": [
    {
      "id": 1,
      "name": "2001",
      "model": "VIVO X200U 16+512",
      "is_accessory": false,
      "status": "online"
    }
  ]
}
```

#### 2. 租赁管理API

##### 创建租赁记录
```http
POST /api/rentals
```

**请求体:**
```json
{
  "device_id": 1,
  "start_date": "2025-01-15",
  "end_date": "2025-01-17",
  "customer_name": "张三",
  "customer_phone": "13800138000",
  "destination": "北京市",
  "accessories": [35, 46]
}
```

##### 获取租赁记录
```http
GET /api/rentals/{rental_id}
```

##### 更新租赁记录
```http
PUT /api/rentals/{rental_id}
```

##### 删除租赁记录
```http
DELETE /api/rentals/{rental_id}
```

##### 更新租赁状态
```http
PUT /api/rentals/{rental_id}/status
```

**请求体:**
```json
{
  "status": "shipped",
  "ship_out_tracking_no": "SF1234567890"
}
```

#### 3. 设备管理API

##### 获取设备列表
```http
GET /api/devices?include_accessories=true
```

##### 获取设备详情
```http
GET /api/devices/{device_id}
```

##### 创建设备
```http
POST /api/devices
```

**请求体:**
```json
{
  "name": "2037",
  "serial_number": "10AF4M00Y6002SP",
  "model": "VIVO X200U 16+512",
  "model_id": 1,
  "is_accessory": false
}
```

##### 更新设备
```http
PUT /api/devices/{device_id}
```

##### 删除设备
```http
DELETE /api/devices/{device_id}
```

#### 4. 设备型号API

##### 获取设备型号列表
```http
GET /api/device-models?include_accessories=true
```

##### 获取型号的附件
```http
GET /api/device-models/{model_id}/accessories
```

#### 5. 甘特图API

##### 获取甘特图数据
```http
GET /api/gantt/data?start_date=2025-01-01&end_date=2025-01-31
```

##### 查找可用时间槽
```http
POST /api/rentals/find-slot
```

**请求体:**
```json
{
  "model_id": 1,
  "duration_days": 3,
  "preferred_date": "2025-01-15"
}
```

##### 获取每日统计
```http
GET /api/gantt/daily-stats?date=2025-01-15
```

#### 6. 统计API

##### 获取最近统计
```http
GET /api/statistics/recent?days=30
```

##### 获取日期范围统计
```http
GET /api/statistics/date-range?start_date=2025-01-01&end_date=2025-01-31
```

##### 获取最新统计
```http
GET /api/statistics/latest
```

##### 计算统计数据
```http
POST /api/statistics/calculate
```

#### 7. 其他API

##### OCR识别身份证
```http
POST /api/ocr/id-card
```

##### 健康检查
```http
GET /health
```

## 数据库设计

### 数据模型关系

```
device_models (设备型号)
    ├── 1:N → devices (设备)
    │         └── 1:N → rentals (租赁记录)
    │                   ├── 1:N → audit_logs (审计日志)
    │                   └── parent_rental_id → rentals (父租赁记录，用于附件关联)
    └── parent_model_id → device_models (自引用，主设备-附件关系)

rental_statistics (租赁统计) - 独立表，定时任务计算生成
```

**关键关系说明:**
1. **设备型号与设备**: 一个型号可以有多个设备实例
2. **主设备与附件**: 通过 device_models.parent_model_id 关联
3. **租赁主从关系**: 通过 rentals.parent_rental_id 关联主设备和附件的租赁
4. **审计日志**: 记录对设备和租赁的所有操作

### 业务状态说明

#### 租赁状态 (rental.status)
- `not_shipped`: 未发货 - 订单已创建，等待发货
- `shipped`: 已发货 - 设备已寄出，客户使用中
- `returned`: 已归还 - 客户已归还，等待验收
- `completed`: 已完成 - 租赁流程完成
- `cancelled`: 已取消 - 订单已取消

#### 设备状态 (device.status)
- `online`: 在线 - 设备正常可用
- `offline`: 离线 - 设备维修或停用

#### 状态流转
```
not_shipped → shipped → returned → completed
              ↓
           cancelled
```

### 主要表结构

#### 设备型号表 (device_models)
```sql
CREATE TABLE device_models (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE COMMENT '型号名称',
    display_name VARCHAR(100) NOT NULL COMMENT '显示名称',
    description TEXT COMMENT '型号描述',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    is_accessory BOOLEAN DEFAULT FALSE COMMENT '是否为附件',
    parent_model_id INT COMMENT '主设备型号ID（如果是附件）',
    default_accessories TEXT COMMENT '默认附件列表，JSON格式',
    device_value DECIMAL(10,2) COMMENT '设备/附件价值',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_model_id) REFERENCES device_models(id)
);
```

#### 设备表 (devices)
```sql
CREATE TABLE devices (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '设备ID',
    name VARCHAR(100) NOT NULL COMMENT '设备名称',
    serial_number VARCHAR(100) UNIQUE COMMENT '设备序列号',
    model VARCHAR(50) NOT NULL DEFAULT 'x200u' COMMENT '设备型号',
    model_id INT COMMENT '设备型号ID',
    is_accessory BOOLEAN DEFAULT FALSE COMMENT '是否为附件',
    status ENUM('online', 'offline') DEFAULT 'online' COMMENT '设备状态',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (model_id) REFERENCES device_models(id)
);
```

#### 租赁记录表 (rentals)
```sql
CREATE TABLE rentals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id INT NOT NULL COMMENT '设备ID',
    start_date DATE NOT NULL COMMENT '开始日期',
    end_date DATE NOT NULL COMMENT '结束日期',
    ship_out_time DATETIME COMMENT '寄出时间',
    ship_in_time DATETIME COMMENT '收回时间',
    customer_name VARCHAR(100) NOT NULL COMMENT '客户姓名',
    customer_phone VARCHAR(20) COMMENT '客户电话',
    destination VARCHAR(100) COMMENT '目的地',
    ship_out_tracking_no VARCHAR(50) COMMENT '寄出快递单号',
    ship_in_tracking_no VARCHAR(50) COMMENT '寄回快递单号',
    status ENUM('not_shipped', 'shipped', 'returned', 'completed', 'cancelled')
        DEFAULT 'not_shipped' COMMENT '租赁状态',
    parent_rental_id INT COMMENT '父租赁记录ID（用于关联主设备和附件）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (parent_rental_id) REFERENCES rentals(id) ON DELETE CASCADE
);
```

#### 审计日志表 (audit_logs)
```sql
CREATE TABLE audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id INT COMMENT '相关设备ID',
    rental_id INT COMMENT '相关租赁ID',
    action VARCHAR(50) NOT NULL COMMENT '操作类型',
    resource_type VARCHAR(50) COMMENT '资源类型',
    resource_id VARCHAR(50) COMMENT '资源ID',
    description TEXT COMMENT '操作描述',
    details JSON COMMENT '操作详情',
    ip_address VARCHAR(45) COMMENT 'IP地址',
    user_agent VARCHAR(500) COMMENT '用户代理',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (rental_id) REFERENCES rentals(id)
);
```

#### 租赁统计表 (rental_statistics)
```sql
CREATE TABLE rental_statistics (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '统计ID',
    stat_date DATE NOT NULL UNIQUE COMMENT '统计日期',
    period_start DATE NOT NULL COMMENT '统计周期开始日期',
    period_end DATE NOT NULL COMMENT '统计周期结束日期',
    total_rentals INT NOT NULL DEFAULT 0 COMMENT '订单总数',
    total_rent DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT '订单总租金',
    total_value DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT '订单总收入价值',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_stat_date (stat_date)
);
```

## 开发指南

### 环境要求
- Python 3.8+
- MySQL 8.0+
- Node.js 18+ (前端开发必需)
- npm 或 pnpm (前端包管理)
- Playwright (PDF生成，会自动安装)

### 开发模式启动

#### 后端开发
```bash
# 设置开发环境变量
export FLASK_ENV=development
export FLASK_DEBUG=1

# 安装Python依赖
pip install -r requirements.txt

# 初始化数据库（首次运行）
python init_db.py

# 启动后端服务
python app.py
```

#### 前端开发
```bash
# 进入前端目录
cd frontend

# 安装依赖
npm install
# 或者使用 pnpm
pnpm install

# 启动开发服务器
npm run dev
# 或者
pnpm dev

# 访问 http://localhost:5173
```

#### 同时开发前后端（使用 Makefile）
```bash
# 同时启动前端和后端开发服务
make dev

# 或者分别启动
make backend    # 启动后端
make frontend   # 启动前端
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

### 生产环境部署

#### 1. 环境准备
```bash
# 克隆代码
git clone <repository-url>
cd InventoryManager

# 配置环境变量
cp env.production .env
# 编辑 .env 文件，设置生产环境配置
```

#### 2. 前端构建
```bash
cd frontend
npm install
npm run build
# 构建产物会输出到 frontend/dist 目录
```

#### 3. Docker部署
```bash
# 使用 Makefile 构建和部署
make docker-build    # 构建镜像
make docker-up       # 启动服务

# 或者直接使用 docker-compose
docker-compose -f docker-compose.yml up -d
```

#### 4. 数据库初始化
```bash
# 进入容器
docker exec -it inventory_manager bash

# 初始化数据库
python init_db.py

# 或者运行迁移
flask db upgrade
```

### 生产环境配置

#### 环境变量配置
1. 修改`.env`文件中的生产环境配置
2. 设置适当的数据库连接池大小
3. 配置日志级别和输出
4. 设置 SECRET_KEY 为随机字符串
5. 配置 CORS 允许的域名

#### Nginx反向代理配置示例
```nginx
server {
    listen 80;
    server_name inventory.example.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /vue/ {
        proxy_pass http://localhost:5000/vue/;
    }

    location /assets/ {
        proxy_pass http://localhost:5000/assets/;
    }
}
```

### 监控和日志
- 应用日志: 容器内 `/app/logs/app.log`
- 健康检查: `/health` 端点
- API文档: `/api/docs` 端点
- 数据库连接检查: 通过健康检查端点

### 定时任务配置
系统使用 APScheduler 进行定时任务调度，包括：
- 每日凌晨计算租赁统计数据
- 定期清理过期数据

查看定时任务状态：
```bash
# 访问统计API查看任务执行情况
curl http://localhost:5000/api/statistics/latest
```

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
