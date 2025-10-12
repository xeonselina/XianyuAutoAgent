#!/usr/bin/env python3
"""
数据库初始化脚本
从 scripts/exported_data.sql 导入数据
"""

import os
import sys

# 必须在导入app之前设置，因为init_db.py在宿主机运行
#os.environ['DATABASE_URL'] = 'mysql+pymysql://root:123456@localhost:3306/testdb'

from app import create_app, db
from sqlalchemy import text

def init_database():
    """初始化数据库"""

    # 创建应用实例
    app = create_app()

    with app.app_context():
        try:
            # 清空数据库（先关闭外键检查，避免删除顺序问题）
            try:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))
                db.session.commit()
            except Exception:
                # 非 MySQL 或权限不足时忽略
                pass

            db.drop_all()
            db.session.commit()
            print("已删除所有表")

            try:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))
                db.session.commit()
            except Exception:
                pass

            # 创建所有表
            db.create_all()
            print("数据库表创建成功")

            # 读取并执行导出的SQL文件
            sql_file_path = os.path.join(os.path.dirname(__file__), 'scripts', 'exported_data.sql')

            if os.path.exists(sql_file_path):
                print(f"正在从 {sql_file_path} 导入数据...")

                with open(sql_file_path, 'r', encoding='utf-8') as f:
                    sql_content = f.read()

                # 移除注释行
                lines = [line for line in sql_content.split('\n')
                        if not line.strip().startswith('--')]
                sql_content = '\n'.join(lines)

                # 按分号分割SQL语句
                sql_statements = [stmt.strip() for stmt in sql_content.split(';')
                                if stmt.strip()]

                # 执行每条SQL语句并统计
                import_stats = {
                    'device_models': 0,
                    'devices': 0,
                    'rentals': 0,
                    'audit_logs': 0,
                    'rental_statistics': 0
                }

                for sql in sql_statements:
                    if sql:
                        try:
                            db.session.execute(text(sql))
                            # 统计各表的导入数量
                            if 'INSERT INTO device_models' in sql:
                                import_stats['device_models'] += 1
                            elif 'INSERT INTO devices' in sql:
                                import_stats['devices'] += 1
                            elif 'INSERT INTO rentals' in sql:
                                import_stats['rentals'] += 1
                            elif 'INSERT INTO audit_logs' in sql:
                                import_stats['audit_logs'] += 1
                            elif 'INSERT INTO rental_statistics' in sql:
                                import_stats['rental_statistics'] += 1
                        except Exception as e:
                            print(f"执行SQL失败: {sql[:100]}... 错误: {e}")

                db.session.commit()

                # 打印导入统计
                print("=" * 50)
                print("数据导入成功！")
                print("-" * 50)
                print(f"设备型号 (device_models):      {import_stats['device_models']} 条")
                print(f"设备 (devices):                {import_stats['devices']} 条")
                print(f"租赁记录 (rentals):            {import_stats['rentals']} 条")
                print(f"审计日志 (audit_logs):         {import_stats['audit_logs']} 条")
                print(f"租赁统计 (rental_statistics):  {import_stats['rental_statistics']} 条")
                print("=" * 50)
            else:
                print(f"警告: 找不到SQL文件 {sql_file_path}")
                print("请先运行: python scripts/export_db_data.py 来生成数据文件")

            print("数据库初始化完成！")

        except Exception as e:
            print(f"数据库初始化失败: {e}")
            import traceback
            traceback.print_exc()
            db.session.rollback()

if __name__ == '__main__':
    init_database()
