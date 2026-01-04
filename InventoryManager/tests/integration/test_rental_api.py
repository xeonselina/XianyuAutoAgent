"""
租赁API集成测试 - 配套附件功能
"""

import pytest
import json
from datetime import date, timedelta
from app.models.device import Device


class TestRentalAPIBundledAccessories:
    """测试租赁API的配套附件功能"""
    
    def test_create_rental_with_bundled_accessories_api(self, client, db_session):
        """测试通过API创建包含配套附件的租赁"""
        # 创建测试设备
        device = Device(
            name='测试相机-API01',
            model='API Test Camera',
            serial_number='ATC-001',
            is_accessory=False
        )
        db_session.add(device)
        db_session.commit()
        
        # API请求数据
        payload = {
            'device_id': device.id,
            'start_date': date.today().isoformat(),
            'end_date': (date.today() + timedelta(days=3)).isoformat(),
            'customer_name': 'API测试客户',
            'customer_phone': '13800138000',
            'destination': '北京市朝阳区',
            # 配套附件（使用布尔值）
            'includes_handle': True,
            'includes_lens_mount': True,
            # 库存附件（空数组）
            'accessories': []
        }
        
        # 发送POST请求
        response = client.post(
            '/api/rentals',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['code'] == 201
        assert 'data' in data
        
        # 验证返回的租赁数据
        main_rental = data['data']['main_rental']
        assert main_rental['includes_handle'] is True
        assert main_rental['includes_lens_mount'] is True
        assert main_rental['customer_name'] == 'API测试客户'
        
        # 验证没有创建库存附件子租赁
        assert len(data['data']['accessory_rentals']) == 0
    
    def test_create_rental_with_inventory_accessories_api(self, client, db_session):
        """测试通过API创建包含库存附件的租赁"""
        # 创建主设备和附件
        main_device = Device(name='相机-API02', is_accessory=False)
        phone_holder = Device(
            name='手机支架-P-API01',
            serial_number='PHAPI-001',
            is_accessory=True
        )
        tripod = Device(
            name='三脚架-T-API01',
            serial_number='TAPI-001',
            is_accessory=True
        )
        
        db_session.add_all([main_device, phone_holder, tripod])
        db_session.commit()
        
        # API请求数据
        payload = {
            'device_id': main_device.id,
            'start_date': date.today().isoformat(),
            'end_date': (date.today() + timedelta(days=5)).isoformat(),
            'customer_name': 'API测试客户2',
            'includes_handle': False,
            'includes_lens_mount': False,
            'accessories': [phone_holder.id, tripod.id]
        }
        
        # 发送请求
        response = client.post(
            '/api/rentals',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        # 验证响应
        assert response.status_code == 201
        data = json.loads(response.data)
        
        main_rental = data['data']['main_rental']
        assert main_rental['includes_handle'] is False
        assert main_rental['includes_lens_mount'] is False
        
        # 验证创建了2个库存附件子租赁
        accessory_rentals = data['data']['accessory_rentals']
        assert len(accessory_rentals) == 2
        accessory_ids = [r['device_id'] for r in accessory_rentals]
        assert phone_holder.id in accessory_ids
        assert tripod.id in accessory_ids
    
    def test_create_rental_with_mixed_accessories_api(self, client, db_session):
        """测试通过API创建同时包含配套和库存附件的租赁"""
        # 创建设备
        main_device = Device(name='相机-API03', is_accessory=False)
        phone_holder = Device(
            name='手机支架-P-API02',
            is_accessory=True
        )
        
        db_session.add_all([main_device, phone_holder])
        db_session.commit()
        
        # 请求数据（同时包含配套和库存附件）
        payload = {
            'device_id': main_device.id,
            'start_date': date.today().isoformat(),
            'end_date': (date.today() + timedelta(days=7)).isoformat(),
            'customer_name': 'API测试客户3',
            'includes_handle': True,  # 配套
            'includes_lens_mount': True,  # 配套
            'accessories': [phone_holder.id]  # 库存
        }
        
        response = client.post(
            '/api/rentals',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        assert response.status_code == 201
        data = json.loads(response.data)
        
        main_rental = data['data']['main_rental']
        # 验证配套附件
        assert main_rental['includes_handle'] is True
        assert main_rental['includes_lens_mount'] is True
        
        # 验证库存附件
        assert len(data['data']['accessory_rentals']) == 1
        assert data['data']['accessory_rentals'][0]['device_id'] == phone_holder.id
    
    def test_update_rental_bundled_accessories_api(self, client, db_session):
        """测试通过API更新配套附件"""
        # 创建设备和初始租赁
        device = Device(name='相机-API04', is_accessory=False)
        db_session.add(device)
        db_session.commit()
        
        # 先创建一个租赁
        create_payload = {
            'device_id': device.id,
            'start_date': date.today().isoformat(),
            'end_date': (date.today() + timedelta(days=3)).isoformat(),
            'customer_name': '更新测试客户',
            'includes_handle': False,
            'includes_lens_mount': False,
            'accessories': []
        }
        
        create_response = client.post(
            '/api/rentals',
            data=json.dumps(create_payload),
            content_type='application/json'
        )
        rental_id = json.loads(create_response.data)['data']['main_rental']['id']
        
        # 更新租赁，添加配套附件
        update_payload = {
            'includes_handle': True,
            'includes_lens_mount': True
        }
        
        update_response = client.put(
            f'/api/rentals/{rental_id}',
            data=json.dumps(update_payload),
            content_type='application/json'
        )
        
        # 验证更新响应
        assert update_response.status_code == 200
        
        # 获取更新后的租赁，验证数据
        get_response = client.get(f'/api/rentals/{rental_id}')
        rental_data = json.loads(get_response.data)['data']
        
        assert rental_data['includes_handle'] is True
        assert rental_data['includes_lens_mount'] is True
    
    def test_get_rental_includes_accessory_info(self, client, db_session):
        """测试获取租赁时包含完整的附件信息"""
        # 创建设备
        main_device = Device(name='相机-API05', is_accessory=False)
        phone_holder = Device(
            name='手机支架-P-API03',
            serial_number='PHAPI-003',
            is_accessory=True
        )
        
        db_session.add_all([main_device, phone_holder])
        db_session.commit()
        
        # 创建租赁（混合附件）
        create_payload = {
            'device_id': main_device.id,
            'start_date': date.today().isoformat(),
            'end_date': (date.today() + timedelta(days=4)).isoformat(),
            'customer_name': '获取测试客户',
            'includes_handle': True,
            'includes_lens_mount': False,
            'accessories': [phone_holder.id]
        }
        
        create_response = client.post(
            '/api/rentals',
            data=json.dumps(create_payload),
            content_type='application/json'
        )
        rental_id = json.loads(create_response.data)['data']['main_rental']['id']
        
        # 获取租赁详情
        get_response = client.get(f'/api/rentals/{rental_id}')
        assert get_response.status_code == 200
        
        rental_data = json.loads(get_response.data)['data']
        
        # 验证基本信息
        assert rental_data['includes_handle'] is True
        assert rental_data['includes_lens_mount'] is False
        
        # 验证accessories字段包含配套和库存附件
        # 注意：具体字段结构取决于to_dict实现
        assert 'accessories' in rental_data or 'child_rentals' in rental_data


@pytest.fixture
def app():
    """创建Flask应用实例"""
    from app import create_app
    app = create_app('testing')
    return app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return app.test_client()


@pytest.fixture
def db_session(app):
    """创建数据库会话"""
    from app import db
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()
