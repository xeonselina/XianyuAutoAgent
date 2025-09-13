#!/usr/bin/env python3
"""
数据库初始化脚本
"""

import os

# 必须在导入app之前设置，因为init_db.py在宿主机运行
#os.environ['DATABASE_URL'] = 'mysql+pymysql://root:123456@localhost:3306/testdb'

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from sqlalchemy import text
from datetime import datetime, date, timedelta

def init_database():
    """初始化数据库"""
    
    # 创建应用实例
    app = create_app()
    
    with app.app_context():
        try:
            # 清空数据库（先关闭外键检查，避免删除顺序问题）
            try:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))
            except Exception:
                # 非 MySQL 或权限不足时忽略
                pass

            db.drop_all()
            db.session.commit()
            print("已删除所有表")

            try:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))
            except Exception:
                pass

            # 创建所有表
            db.create_all()
            print("数据库表创建成功")
            
            
            # 导入真实设备和租赁数据
            print("正在导入真实设备和租赁数据...")
            # 导入设备数据
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (1, '2001', '10AF4C15P8002JU', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 05:40:00');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (2, '2002', '10AF4F2N88002K0', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:08:29');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (3, '2003', '10AF5R2EJC003GQ', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:17:17');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (4, '2004', '10AF6C23YF0040C', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:28:02');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (5, '2005', '10AF4D034M002LD', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:29:46');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (6, '2006', '10AF4U05QK002ZB', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:31:37');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (7, '2007', '10AF5X2HDQ003M7', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:34:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (8, '2008', '10AF7H1QM0004Y6', 'x200u', FALSE, 'pending_return', '2025-08-26 11:44:07', '2025-08-27 06:36:03');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (9, '2009', '10AF7423K3004PL', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:37:11');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (10, '2010', '10AF4U0FMT002ZB', 'x200u', FALSE, 'renting', '2025-08-26 11:44:07', '2025-08-27 06:38:13');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (11, '2011', '10AF561KHA0035K', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (12, '2012', '10AF3S0EQQ00206', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (13, '2013', '10AF4U0D60002ZB', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (14, '2014', '10AF6K10B30046N', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (15, '2015', '10AF6MOPF00049M', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (16, '2016', '10AF6D0Q7800439', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (17, '2017', '10AF4F0A99002K0', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (18, '2018', '10AF571CSR00375', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (19, '2019', '10AF6S304P004E9', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (20, '2020', '10AF4COULP002JU', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (21, '2021', '10AF6MOPDK0049M', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (22, '2022', '10AF4N0BXU002NC', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (23, '2023', '10AF771R44004NB', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (24, '2024', '10AF6S301B004E9', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (25, '2025', '10AF5L1X57003DR', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (26, '2026', '10AF460K5G002E9', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (27, '2027', '2027', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (28, '2028', '2028', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (29, '2029', '2029', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (30, '2030', '2030', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (31, '2031', '2031', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (32, '2032', '2032', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (33, '2033', '2033', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))
            db.session.execute(text("INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES (34, '2034', '2034', 'x200u', FALSE, 'idle', '2025-08-26 11:44:07', '2025-08-26 11:44:07');"))

            # 导入租赁数据(添加parent_rental_id字段)
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (1, 1, '2025-08-31', '2025-08-31', '2025-08-29 08:00:00', '2025-09-02 08:00:00', '呆毛飘飘', '18145718032', 'Carey，18145718032，广东省广州市越秀区大塘街道会同里16号', NULL, NULL, 'pending', NULL, '2025-08-27 05:40:00', '2025-08-27 05:40:00');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (2, 2, '2025-08-29', '2025-08-30', '2025-08-26 00:00:00', '2025-09-01 00:00:00', '偷你小拖把', '13143594307', '小八,13143594307,广东省佛山市南海区桂城街道翠湖新村2号楼B座202', '', '', 'pending', NULL, '2025-08-27 06:08:29', '2025-08-27 06:25:42');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (3, 3, '2025-08-28', '2025-08-31', '2025-08-26 00:00:00', '2025-09-02 00:00:00', 'Recall', '15687462960', '吴远芳,15687462960,云南省昆明市官渡区金马街道东华小区夏荫里7栋1单元502', '', '', 'pending', NULL, '2025-08-27 06:17:17', '2025-08-27 06:26:04');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (4, 4, '2025-08-27', '2025-08-31', '2025-08-26 14:26:00', '2025-09-02 14:26:00', '小九1005', '13828791009', '刘小姐,13828791009,广东省深圳市南山区蛇口街道中心路卓越维港南区13栋5A2', '', '', 'pending', NULL, '2025-08-27 06:28:02', '2025-08-27 06:28:25');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (5, 5, '2025-08-27', '2025-08-28', '2025-08-26 14:28:00', '2025-08-30 14:28:00', 'W1ingson', '13073076032', '陈业恒,13073076032,广东省佛山市南海区丹灶镇有为大道28号伙伙乐港式猪扒包', '', '', 'pending', NULL, '2025-08-27 06:29:46', '2025-08-27 06:30:27');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (6, 6, '2025-08-29', '2025-09-02', '2025-08-28 14:30:00', '2025-09-03 14:30:00', '勋诗', '13570276890', '湿湿,13570276890,广东省广州市南沙区大岗镇灵山江滘路81号', NULL, NULL, 'pending', NULL, '2025-08-27 06:31:37', '2025-08-27 06:31:37');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (7, 6, '2025-09-05', '2025-09-05', '2025-09-03 14:32:00', '2025-09-07 14:32:00', '阿***儿', '13018738552', '杨小姐,13018738552,广东省中山市东区街道银湾南路106号 顺景蔷薇山庄第四期50栋', NULL, NULL, 'pending', NULL, '2025-08-27 06:32:54', '2025-08-27 06:32:54');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (8, 7, '2025-08-30', '2025-08-31', '2025-08-28 14:33:00', '2025-09-02 14:33:00', '不看文案一律拉黑', '13502528569', '贝壳,13502528569,广东省梅州市兴宁市兴田街道团结路怡华苑', NULL, NULL, 'pending', NULL, '2025-08-27 06:34:07', '2025-08-27 06:34:07');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (9, 8, '2025-08-27', '2025-08-27', '2025-08-25 14:34:00', '2025-08-29 14:34:00', '咸鱼卖东西的第三年', '13652965669', '黄泽广,13652965669,广东省揭阳市普宁市流沙西街道赤水顶山乾拆迁楼东普宁大道北骆驼移门往前50米看到别墅拐进来有车棚这栋（直接放绿色防盗门里面）', NULL, NULL, 'pending', NULL, '2025-08-27 06:35:50', '2025-08-27 06:35:50');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (10, 9, '2025-08-28', '2025-08-31', '2025-08-26 14:36:00', '2025-09-02 14:36:00', '想当昏头鱼', '13767888460', '昏昏,13767888460,北京北京市海淀区八里庄街道西翠路定慧东里2号楼4单元307', NULL, NULL, 'pending', NULL, '2025-08-27 06:37:11', '2025-08-27 06:37:11');"))
            db.session.execute(text("INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES (11, 10, '2025-08-28', '2025-08-29', '2025-08-27 14:37:00', '2025-08-30 14:37:00', '养了一只pizza', '13246009867', '陈村粉,13246009867,广东省中山市火炬开发区街道康乐大道33号行政服务中心', NULL, NULL, 'pending', NULL, '2025-08-27 06:38:13', '2025-08-27 06:38:13');"))

            # 提交所有导入的数据
            db.session.commit()
            print("数据导入成功")
            
            print("数据库初始化完成！")
            
        except Exception as e:
            print(f"数据库初始化失败: {e}")
            db.session.rollback()

if __name__ == '__main__':
    init_database()
