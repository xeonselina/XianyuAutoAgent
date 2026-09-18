# MySQL连接示例

## 1. Python PyMySQL 连接

```python
import pymysql

# 方式1: 分参数
connection = pymysql.connect(
    host='127.0.0.1',
    port=3306,
    user='root',
    password='123456',
    database='testdb'  # 可选，如果数据库不存在会报错
)

# 方式2: 连接字符串
DATABASE_URL = 'mysql+pymysql://root:123456@127.0.0.1:3306/testdb'
```

## 2. MySQL命令行客户端

```bash
# 方式1
mysql -h 127.0.0.1 -P 3306 -u root -p123456 testdb

# 方式2 (会提示输入密码)
mysql -h 127.0.0.1 -P 3306 -u root -p testdb
```

## 3. 使用Docker执行MySQL命令

```bash
# 在MySQL容器内执行
docker exec mysql-local mysql -u root -p123456 -e "SHOW DATABASES;"

# 连接到外部MySQL (从其他容器)
docker run --rm mysql:8.0 mysql -h host.docker.internal -P 3306 -u root -p123456 -e "SELECT 1;"
```

## 4. 常见错误格式

❌ **错误**：
- `root@123456@127.0.0.1:3306`
- `127.0.0.1:3306 root@123456`
- `mysql://root@123456:127.0.0.1:3306/testdb`

✅ **正确**：
- `mysql+pymysql://root:123456@127.0.0.1:3306/testdb`
- 分离参数: host='127.0.0.1', user='root', password='123456'