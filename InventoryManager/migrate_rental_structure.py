#!/usr/bin/env python3
"""
独立的数据库迁移脚本：从 rental_accessories 迁移到 parent_rental_id 架构

这个脚本会：
1. 为 rentals 表添加 parent_rental_id 字段（如果不存在）
2. 将 rental_accessories 表中的数据转换为独立的 Rental 记录
3. 删除 rental_accessories 表

运行方式：
python migrate_rental_structure.py

"""

import os
import sys
from datetime import datetime
from sqlalchemy import create_engine, text, inspect, MetaData
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

def create_db_engine():
    """创建数据库引擎"""
    # 从环境变量或配置文件读取数据库URL
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        print("❌ 未找到 DATABASE_URL 环境变量")
        print("请设置环境变量，例如：")
        print("export DATABASE_URL='mysql+pymysql://user:password@host:port/database'")
        print("或")
        print("export DATABASE_URL='sqlite:///inventory_management.db'")
        sys.exit(1)
    
    print(f"🔗 连接数据库: {database_url.replace(database_url.split('@')[0].split('//')[-1], '***:***')}")
    
    try:
        engine = create_engine(database_url)
        # 测试连接
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ 数据库连接成功")
        return engine
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        sys.exit(1)

def check_table_exists(engine, table_name):
    """检查表是否存在"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def check_column_exists(engine, table_name, column_name):
    """检查列是否存在"""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns

def add_parent_rental_id_column(engine):
    """添加 parent_rental_id 字段"""
    print("\n📝 步骤1: 添加 parent_rental_id 字段")
    
    if not check_table_exists(engine, 'rentals'):
        print("❌ rentals 表不存在")
        return False
        
    if check_column_exists(engine, 'rentals', 'parent_rental_id'):
        print("✅ parent_rental_id 字段已存在，跳过添加")
        return True
    
    try:
        with engine.connect() as conn:
            # 添加字段
            conn.execute(text("""
                ALTER TABLE rentals 
                ADD COLUMN parent_rental_id INT NULL 
                COMMENT '父租赁记录ID（用于关联主设备和附件）'
            """))
            
            # 添加外键约束
            conn.execute(text("""
                ALTER TABLE rentals 
                ADD CONSTRAINT fk_rentals_parent_rental_id 
                FOREIGN KEY (parent_rental_id) REFERENCES rentals(id)
            """))
            
            conn.commit()
            print("✅ parent_rental_id 字段添加成功")
            return True
    except Exception as e:
        print(f"❌ 添加 parent_rental_id 字段失败: {e}")
        return False

def migrate_rental_accessories_data(engine):
    """迁移 rental_accessories 数据"""
    print("\n🔄 步骤2: 迁移 rental_accessories 数据")
    
    if not check_table_exists(engine, 'rental_accessories'):
        print("✅ rental_accessories 表不存在，无需迁移")
        return True
    
    try:
        with engine.connect() as conn:
            # 查询需要迁移的数据
            result = conn.execute(text("""
                SELECT ra.id, ra.rental_id, ra.device_id, ra.created_at, ra.updated_at,
                       r.start_date, r.end_date, r.customer_name, r.customer_phone, 
                       r.destination, r.status, r.ship_out_time, r.ship_in_time
                FROM rental_accessories ra
                JOIN rentals r ON ra.rental_id = r.id
                ORDER BY ra.rental_id, ra.id
            """))
            
            accessories_data = result.fetchall()
            
            if not accessories_data:
                print("✅ rental_accessories 表为空，无需迁移")
                return True
            
            print(f"📊 发现 {len(accessories_data)} 条附件租赁记录需要迁移")
            
            migrated_count = 0
            failed_count = 0
            
            for row in accessories_data:
                try:
                    # 为每个附件创建独立的租赁记录
                    conn.execute(text("""
                        INSERT INTO rentals (
                            device_id, start_date, end_date, customer_name, customer_phone,
                            destination, status, ship_out_time, ship_in_time,
                            parent_rental_id, created_at, updated_at
                        ) VALUES (
                            :device_id, :start_date, :end_date, :customer_name, :customer_phone,
                            :destination, :status, :ship_out_time, :ship_in_time,
                            :parent_rental_id, :created_at, :updated_at
                        )
                    """), {
                        'device_id': row.device_id,
                        'start_date': row.start_date,
                        'end_date': row.end_date,
                        'customer_name': row.customer_name,
                        'customer_phone': row.customer_phone,
                        'destination': row.destination,
                        'status': row.status,
                        'ship_out_time': row.ship_out_time,
                        'ship_in_time': row.ship_in_time,
                        'parent_rental_id': row.rental_id,
                        'created_at': row.created_at,
                        'updated_at': row.updated_at
                    })
                    migrated_count += 1
                    print(f"  ✅ 迁移: 设备 {row.device_id} -> 主租赁 {row.rental_id}")
                except Exception as e:
                    failed_count += 1
                    print(f"  ❌ 迁移失败: 设备 {row.device_id}, 错误: {e}")
            
            conn.commit()
            print(f"✅ 数据迁移完成: 成功 {migrated_count} 条, 失败 {failed_count} 条")
            return failed_count == 0
            
    except Exception as e:
        print(f"❌ 数据迁移失败: {e}")
        return False

def drop_rental_accessories_table(engine):
    """删除 rental_accessories 表"""
    print("\n🗑️  步骤3: 删除 rental_accessories 表")
    
    if not check_table_exists(engine, 'rental_accessories'):
        print("✅ rental_accessories 表已不存在")
        return True
    
    try:
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE rental_accessories"))
            conn.commit()
            print("✅ rental_accessories 表删除成功")
            return True
    except Exception as e:
        print(f"❌ 删除 rental_accessories 表失败: {e}")
        return False

def verify_migration(engine):
    """验证迁移结果"""
    print("\n✅ 步骤4: 验证迁移结果")
    
    try:
        with engine.connect() as conn:
            # 检查 parent_rental_id 字段
            if not check_column_exists(engine, 'rentals', 'parent_rental_id'):
                print("❌ parent_rental_id 字段不存在")
                return False
            print("✅ parent_rental_id 字段存在")
            
            # 检查子租赁记录数量
            result = conn.execute(text("SELECT COUNT(*) FROM rentals WHERE parent_rental_id IS NOT NULL"))
            child_count = result.scalar()
            print(f"✅ 子租赁记录数量: {child_count}")
            
            # 检查主租赁记录数量
            result = conn.execute(text("SELECT COUNT(*) FROM rentals WHERE parent_rental_id IS NULL"))
            main_count = result.scalar()
            print(f"✅ 主租赁记录数量: {main_count}")
            
            # 检查 rental_accessories 表是否已删除
            if check_table_exists(engine, 'rental_accessories'):
                print("⚠️ rental_accessories 表仍然存在")
                return False
            print("✅ rental_accessories 表已删除")
            
            return True
    except Exception as e:
        print(f"❌ 验证失败: {e}")
        return False

def main():
    """主函数"""
    print("🚀 开始租赁架构迁移")
    print("=" * 50)
    
    # 创建数据库引擎
    engine = create_db_engine()
    
    # 执行迁移步骤
    success = True
    
    # 步骤1: 添加 parent_rental_id 字段
    if not add_parent_rental_id_column(engine):
        success = False
    
    # 步骤2: 迁移数据
    if success and not migrate_rental_accessories_data(engine):
        success = False
    
    # 步骤3: 删除旧表
    if success and not drop_rental_accessories_table(engine):
        success = False
    
    # 步骤4: 验证迁移
    if success and not verify_migration(engine):
        success = False
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 迁移成功完成！")
        print("\n新架构说明:")
        print("- 附件租赁现在作为独立的 Rental 记录存储")
        print("- parent_rental_id 字段用于关联主设备和附件租赁")
        print("- parent_rental_id 为 NULL 的是主租赁记录")
        print("- parent_rental_id 不为 NULL 的是附件租赁记录")
    else:
        print("❌ 迁移过程中出现错误，请检查日志")
        sys.exit(1)

if __name__ == "__main__":
    main()