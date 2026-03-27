"""
环境配置检查脚本
检查 MySQL、API Key 等必需的配置是否正确
"""

import os
import sys
import pymysql

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from ai_kefu.config.settings import settings


def check_mysql():
    """检查 MySQL 连接"""
    print("=" * 60)
    print("检查 MySQL 配置")
    print("=" * 60)
    print(f"主机: {settings.mysql_host}")
    print(f"端口: {settings.mysql_port}")
    print(f"用户: {settings.mysql_user}")
    print(f"密码: {'*' * len(settings.mysql_password) if settings.mysql_password else '(未设置)'}")
    print(f"数据库: {settings.mysql_database}")
    print()
    
    if not settings.mysql_user:
        print("❌ MySQL 用户名未设置")
        print("提示: 请在 .env 文件中设置 MYSQL_USER")
        return False
    
    if not settings.mysql_password:
        print("⚠️  警告: MySQL 密码未设置")
        print("提示: 如果需要密码，请在 .env 文件中设置 MYSQL_PASSWORD")
    
    try:
        print("尝试连接 MySQL...")
        connection = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            charset='utf8mb4'
        )
        
        cursor = connection.cursor()
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        print(f"✅ MySQL 连接成功！版本: {version[0]}")
        
        # 检查数据库是否存在
        cursor.execute("SHOW DATABASES LIKE %s", (settings.mysql_database,))
        result = cursor.fetchone()
        
        if result:
            print(f"✅ 数据库 '{settings.mysql_database}' 已存在")
        else:
            print(f"⚠️  数据库 '{settings.mysql_database}' 不存在")
            print(f"提示: 运行 init_rental_knowledge.py 脚本时会自动创建")
        
        cursor.close()
        connection.close()
        return True
        
    except pymysql.MySQLError as e:
        print(f"❌ MySQL 连接失败: {e}")
        print()
        print("可能的原因:")
        print("1. MySQL 服务未启动")
        print("   macOS: brew services start mysql")
        print("   Linux: sudo systemctl start mysql")
        print("2. 用户名或密码错误")
        print("3. MySQL 端口不是 3306")
        print("4. MySQL 不允许从当前主机连接")
        return False
    except Exception as e:
        print(f"❌ 连接错误: {e}")
        return False


def check_api_key():
    """检查 API Key"""
    print()
    print("=" * 60)
    print("检查通义千问 API Key")
    print("=" * 60)
    
    if not settings.api_key or settings.api_key == "your_api_key_here":
        print("❌ API Key 未设置或使用默认占位符")
        print()
        print("请按以下步骤获取 API Key:")
        print("1. 访问 https://dashscope.console.aliyun.com/")
        print("2. 登录阿里云账号")
        print("3. 创建 API Key")
        print("4. 将 API Key 添加到 .env 文件:")
        print("   API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        return False
    
    print(f"API Key: {settings.api_key[:10]}...{settings.api_key[-4:]}")
    print(f"模型名称: {settings.model_name}")
    print(f"API 地址: {settings.model_base_url}")
    print()
    print("✅ API Key 已配置")
    print("注意: 需要实际调用 API 才能验证 Key 是否有效")
    return True


def main():
    """主函数"""
    print()
    print("🔍 闲鱼 AI 客服环境配置检查")
    print()
    
    mysql_ok = check_mysql()
    api_key_ok = check_api_key()
    
    print()
    print("=" * 60)
    print("检查结果")
    print("=" * 60)
    
    if mysql_ok and api_key_ok:
        print("✅ 所有配置检查通过！")
        print()
        print("下一步:")
        print("  python3 scripts/init_rental_knowledge.py")
        return 0
    else:
        print("❌ 部分配置存在问题，请根据上述提示进行修复")
        return 1


if __name__ == "__main__":
    sys.exit(main())
