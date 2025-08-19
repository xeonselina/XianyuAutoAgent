#!/usr/bin/env python3
"""
测试数据库连接
"""

import os
import sys

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 设置默认环境变量（如果 .env 中没有设置）
os.environ.setdefault('DATABASE_URL', 'mysql+pymysql://root:123456@localhost:3306/testdb')
os.environ.setdefault('APP_PORT', '5001')

# 添加项目路径到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_connection():
    """测试数据库连接"""
    try:
        print("测试数据库连接...")
        print(f"DATABASE_URL: {os.environ.get('DATABASE_URL')}")
        
        from app import create_app
        app = create_app()
        
        with app.app_context():
            from app.models.device import Device
            device_count = Device.query.count()
            print(f"✅ 数据库连接成功！")
            print(f"当前设备数量: {device_count}")
            return True
            
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return False

if __name__ == '__main__':
    test_connection()
