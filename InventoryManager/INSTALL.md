# 库存管理系统安装说明

## 快速安装

### 1. 克隆项目
```bash
git clone <repository-url>
cd InventoryManager
```

### 2. 安装依赖（推荐使用开发版本）
```bash
# 使用开发依赖文件，避免gevent编译问题
pip install -r requirements-dev.txt
```

### 3. 配置环境
```bash
cp env.local .env
nano .env  # 编辑数据库配置
```

### 4. 启动应用
```bash
python app.py
```

## 解决gevent编译问题

如果您遇到gevent编译失败，请使用以下方法：

### 方法1：使用开发依赖（推荐）
```bash
pip install -r requirements-dev.txt
```

### 方法2：跳过有问题的包
```bash
pip install Flask==2.3.3 Flask-SQLAlchemy==3.0.5 Flask-Migrate==4.0.5
pip install PyMySQL==1.1.0 cryptography==41.0.7
pip install pandas==2.1.1 openpyxl==3.1.2
pip install python-dotenv==1.0.0 loguru==0.7.2
```

### 方法3：使用替代方案
```bash
pip install eventlet==0.33.3  # 替代gevent
```

## 数据库配置

### SQLite（开发环境，简单）
```bash
# 在.env文件中设置
DATABASE_URL=sqlite:///inventory_management.db
```

### MySQL（生产环境）
```bash
# 在.env文件中设置
DATABASE_URL=mysql+pymysql://username:password@host:port/database
```

## 启动应用

```bash
# 开发模式
python app.py

# 生产模式
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## 访问应用

- Web界面: http://localhost:5000
- 健康检查: http://localhost:5000/health

## 常见问题

1. **gevent编译失败**：使用 `requirements-dev.txt`
2. **数据库连接失败**：检查数据库服务和连接字符串
3. **权限问题**：使用虚拟环境或 `--user` 参数

详细说明请参考 `docs/` 目录下的文档。
