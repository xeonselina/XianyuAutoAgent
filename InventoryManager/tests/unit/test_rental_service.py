"""
租赁服务单元测试 - 配套附件功能
"""

import pytest
from datetime import date, timedelta
from app.models.rental import Rental
from app.models.device import Device
from app.services.rental.rental_service import RentalService


class TestRentalServiceBundledAccessories:
    """测试租赁服务的配套附件功能"""
    
    def test_create_rental_with_bundled_accessories(self, app, db_session):
        """测试创建包含配套附件的租赁"""
        with app.app_context():
            # 创建测试设备
            device = Device(
                name='测试相机-A01',
                model='Test Camera',
                serial_number='TC-001',
                is_accessory=False
            )
            db_session.add(device)
            db_session.commit()
            
            # 创建租赁数据
            rental_data = {
                'device_id': device.id,
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=3),
                'customer_name': '测试客户',
                'customer_phone': '13800138000',
                'destination': '北京市',
                # 配套附件标记
                'includes_handle': True,
                'includes_lens_mount': True,
                'accessories': []  # 无库存附件
            }
            
            # 创建租赁
            main_rental, accessory_rentals = RentalService.create_rental_with_accessories(rental_data)
            
            # 验证主租赁记录
            assert main_rental is not None
            assert main_rental.includes_handle is True
            assert main_rental.includes_lens_mount is True
            assert main_rental.customer_name == '测试客户'
            
            # 验证没有创建子租赁记录（因为是配套附件）
            assert len(accessory_rentals) == 0
    
    def test_create_rental_with_inventory_accessories(self, app, db_session):
        """测试创建包含库存附件的租赁"""
        with app.app_context():
            # 创建主设备
            main_device = Device(
                name='测试相机-A02',
                model='Test Camera',
                serial_number='TC-002',
                is_accessory=False
            )
            
            # 创建库存附件（手机支架）
            phone_holder = Device(
                name='手机支架-P01',
                model='Phone Holder',
                serial_number='PH-001',
                is_accessory=True
            )
            
            db_session.add_all([main_device, phone_holder])
            db_session.commit()
            
            # 创建租赁数据
            rental_data = {
                'device_id': main_device.id,
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=5),
                'customer_name': '测试客户2',
                'customer_phone': '13900139000',
                'destination': '上海市',
                'includes_handle': False,
                'includes_lens_mount': False,
                'accessories': [phone_holder.id]
            }
            
            # 创建租赁
            main_rental, accessory_rentals = RentalService.create_rental_with_accessories(rental_data)
            
            # 验证主租赁
            assert main_rental is not None
            assert main_rental.includes_handle is False
            assert main_rental.includes_lens_mount is False
            
            # 验证创建了子租赁记录（库存附件）
            assert len(accessory_rentals) == 1
            assert accessory_rentals[0].device_id == phone_holder.id
            assert accessory_rentals[0].parent_rental_id == main_rental.id
    
    def test_create_rental_with_mixed_accessories(self, app, db_session):
        """测试创建同时包含配套和库存附件的租赁"""
        with app.app_context():
            # 创建设备
            main_device = Device(
                name='测试相机-A03',
                model='Test Camera',
                is_accessory=False
            )
            tripod = Device(
                name='三脚架-T01',
                model='Tripod',
                is_accessory=True
            )
            
            db_session.add_all([main_device, tripod])
            db_session.commit()
            
            # 创建租赁数据（同时包含配套和库存附件）
            rental_data = {
                'device_id': main_device.id,
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=7),
                'customer_name': '测试客户3',
                'includes_handle': True,  # 配套
                'includes_lens_mount': True,  # 配套
                'accessories': [tripod.id]  # 库存
            }
            
            # 创建租赁
            main_rental, accessory_rentals = RentalService.create_rental_with_accessories(rental_data)
            
            # 验证配套附件标记
            assert main_rental.includes_handle is True
            assert main_rental.includes_lens_mount is True
            
            # 验证库存附件子租赁
            assert len(accessory_rentals) == 1
            assert accessory_rentals[0].device_id == tripod.id
    
    def test_get_all_accessories_for_display(self, app, db_session):
        """测试获取所有附件信息的显示方法"""
        with app.app_context():
            # 创建设备
            main_device = Device(name='相机', is_accessory=False)
            phone_holder = Device(
                name='手机支架-P02',
                serial_number='PH-002',
                is_accessory=True
            )
            
            db_session.add_all([main_device, phone_holder])
            db_session.commit()
            
            # 创建主租赁
            main_rental = Rental(
                device_id=main_device.id,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=3),
                customer_name='测试客户',
                includes_handle=True,
                includes_lens_mount=False,
                status='not_shipped'
            )
            db_session.add(main_rental)
            db_session.flush()
            
            # 创建库存附件子租赁
            child_rental = Rental(
                device_id=phone_holder.id,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=3),
                customer_name='测试客户',
                parent_rental_id=main_rental.id,
                status='not_shipped'
            )
            db_session.add(child_rental)
            db_session.commit()
            
            # 获取所有附件
            all_accessories = main_rental.get_all_accessories_for_display()
            
            # 验证返回的附件列表
            assert len(all_accessories) == 2
            
            # 查找配套附件
            bundled = [a for a in all_accessories if a.get('is_bundled')]
            assert len(bundled) == 1
            assert bundled[0]['name'] == '手柄'
            assert bundled[0]['type'] == 'handle'
            
            # 查找库存附件
            inventory = [a for a in all_accessories if not a.get('is_bundled')]
            assert len(inventory) == 1
            assert inventory[0]['name'] == '手机支架-P02'
            assert inventory[0]['serial_number'] == 'PH-002'
            assert inventory[0]['type'] == 'phone_holder'
    
    def test_update_rental_with_accessories(self, app, db_session):
        """测试更新租赁的附件（包括配套附件）"""
        with app.app_context():
            # 创建设备
            main_device = Device(name='相机', is_accessory=False)
            db_session.add(main_device)
            db_session.commit()
            
            # 创建初始租赁（不含附件）
            rental = Rental(
                device_id=main_device.id,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=5),
                customer_name='客户A',
                includes_handle=False,
                includes_lens_mount=False,
                status='not_shipped'
            )
            db_session.add(rental)
            db_session.commit()
            
            # 更新租赁，添加配套附件
            update_data = {
                'includes_handle': True,
                'includes_lens_mount': True
            }
            
            updated_rental = RentalService.update_rental_with_accessories(rental.id, update_data)
            
            # 验证更新结果
            assert updated_rental.includes_handle is True
            assert updated_rental.includes_lens_mount is True


@pytest.fixture
def app():
    """创建Flask应用测试实例"""
    from app import create_app
    app = create_app('testing')
    return app


@pytest.fixture
def db_session(app):
    """创建数据库会话"""
    from app import db
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()
