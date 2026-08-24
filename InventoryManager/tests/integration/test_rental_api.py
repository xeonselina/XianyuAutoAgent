"""
租赁API集成测试 - 配套附件功能
"""

import pytest
import json
from datetime import date, timedelta
from app.models.device import Device
from app.models.rental import Rental
from app.services.scheduling import USAGE_PERIOD_CONFLICT


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
        assert data['success'] is True
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


class TestRentalAPIFinalUsagePeriodGuard:
    @pytest.mark.parametrize(
        'route_template',
        (
            '/api/rentals/{id}/ship-to-xianyu',
            '/api/shipping-batch/ship-to-xianyu/{id}',
        ),
    )
    def test_xianyu_final_write_syncs_locked_parent_child_group(
        self,
        client,
        db_session,
        monkeypatch,
        route_template,
    ):
        main_device = Device(name='闲鱼最终写主设备', is_accessory=False)
        accessory = Device(name='闲鱼最终写附件', is_accessory=True)
        db_session.add_all([main_device, accessory])
        db_session.flush()
        main = Rental(
            device_id=main_device.id,
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=7),
            customer_name='闲鱼最终写客户',
            xianyu_order_no='XY-FINAL-WRITE',
            ship_out_tracking_no='SF-FINAL-WRITE',
            status='not_shipped',
        )
        db_session.add(main)
        db_session.flush()
        child = Rental(
            device_id=accessory.id,
            start_date=main.start_date,
            end_date=main.end_date,
            customer_name=main.customer_name,
            parent_rental_id=main.id,
            status='not_shipped',
        )
        db_session.add(child)
        db_session.commit()

        class FakeXianyuService:
            def ship_order(self, _rental):
                return {'success': True, 'data': {'accepted': True}}

        monkeypatch.setattr(
            'app.services.xianyu_order_service.get_xianyu_service',
            lambda: FakeXianyuService(),
        )

        response = client.post(route_template.format(id=main.id))

        assert response.status_code == 200
        db_session.expire_all()
        persisted_main = db_session.get(Rental, main.id)
        persisted_child = db_session.get(Rental, child.id)
        assert persisted_main.status == 'shipped'
        assert persisted_main.actual_shipped_at == persisted_main.ship_out_time
        assert persisted_main.actual_shipped_at is not None
        assert persisted_child.status == 'shipped'
        assert persisted_child.actual_shipped_at == persisted_child.ship_out_time
        assert persisted_child.actual_shipped_at is not None

    @pytest.mark.parametrize(
        'route_template',
        (
            '/api/rentals/{id}/ship-to-xianyu',
            '/api/shipping-batch/ship-to-xianyu/{id}',
        ),
    )
    def test_xianyu_child_id_is_rejected_before_provider_call(
        self,
        client,
        db_session,
        monkeypatch,
        route_template,
    ):
        main_device = Device(name='附件入口主设备', is_accessory=False)
        accessory = Device(name='附件入口附件', is_accessory=True)
        db_session.add_all([main_device, accessory])
        db_session.flush()
        main = Rental(
            device_id=main_device.id,
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=7),
            customer_name='附件入口客户',
            status='not_shipped',
        )
        db_session.add(main)
        db_session.flush()
        child = Rental(
            device_id=accessory.id,
            start_date=main.start_date,
            end_date=main.end_date,
            customer_name=main.customer_name,
            xianyu_order_no='XY-CHILD',
            ship_out_tracking_no='SF-CHILD',
            parent_rental_id=main.id,
            status='not_shipped',
        )
        db_session.add(child)
        db_session.commit()
        provider_calls = []

        class FakeXianyuService:
            def ship_order(self, _rental):
                provider_calls.append(True)
                return {'success': True}

        monkeypatch.setattr(
            'app.services.xianyu_order_service.get_xianyu_service',
            lambda: FakeXianyuService(),
        )

        response = client.post(route_template.format(id=child.id))

        assert response.status_code == 400
        assert provider_calls == []
        db_session.refresh(child)
        assert child.status == 'not_shipped'

    def test_logistics_facts_flow_through_create_update_and_status_routes(
        self,
        client,
        db_session,
    ):
        device = Device(name='API物流事实设备', is_accessory=False)
        db_session.add(device)
        db_session.commit()
        start_date = date.today() + timedelta(days=10)
        end_date = start_date + timedelta(days=2)

        create_response = client.post(
            '/api/rentals',
            json={
                'device_id': device.id,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'customer_name': 'API物流事实客户',
                'logistics_days': 0,
                'photo_transfer': True,
                'accessories': [],
            },
        )

        assert create_response.status_code == 201
        created = create_response.get_json()['data']['main_rental']
        assert created['logistics_days'] == 0
        assert created['planned_ship_out_date'] == (
            start_date - timedelta(days=1)
        ).isoformat()
        assert created['planned_return_date'] == (
            end_date + timedelta(days=1)
        ).isoformat()
        assert created['photo_transfer'] is True
        rental_id = created['id']

        new_start = start_date + timedelta(days=5)
        new_end = end_date + timedelta(days=6)
        update_response = client.put(
            f'/api/rentals/{rental_id}',
            json={
                'start_date': new_start.isoformat(),
                'end_date': new_end.isoformat(),
                'logistics_days': 2,
            },
        )
        assert update_response.status_code == 200

        shipped_response = client.put(
            f'/api/rentals/{rental_id}/status',
            json={'status': 'shipped'},
        )
        assert shipped_response.status_code == 200
        returned_response = client.put(
            f'/api/rentals/{rental_id}/status',
            json={'status': 'returned'},
        )
        assert returned_response.status_code == 200

        persisted = client.get(f'/api/rentals/{rental_id}').get_json()['data']
        assert persisted['logistics_days'] == 2
        assert persisted['planned_ship_out_date'] == (
            new_start - timedelta(days=3)
        ).isoformat()
        assert persisted['planned_return_date'] == (
            new_end + timedelta(days=3)
        ).isoformat()
        assert persisted['actual_shipped_at'] == persisted['ship_out_time']
        assert persisted['actual_returned_at'] == persisted['ship_in_time']

    def test_create_route_returns_stable_409_and_writes_nothing(
        self,
        client,
        db_session,
    ):
        device = Device(name='创建路由冲突设备', is_accessory=False)
        db_session.add(device)
        db_session.flush()
        existing = Rental(
            device_id=device.id,
            start_date=date.today() + timedelta(days=2),
            end_date=date.today() + timedelta(days=4),
            customer_name='已有客户',
            status='not_shipped',
        )
        db_session.add(existing)
        db_session.commit()
        existing_id = existing.id

        response = client.post(
            '/api/rentals',
            json={
                'device_id': device.id,
                'start_date': (
                    date.today() + timedelta(days=4)
                ).isoformat(),
                'end_date': (
                    date.today() + timedelta(days=6)
                ).isoformat(),
                'customer_name': '不得写入的客户',
                'accessories': [],
            },
        )

        assert response.status_code == 409
        assert response.get_json() == {
            'success': False,
            'message': '租赁档期冲突',
            'data': {
                'code': USAGE_PERIOD_CONFLICT,
                'conflicting_rental_ids': [existing_id],
            },
        }
        db_session.expire_all()
        assert [row.id for row in Rental.query.all()] == [existing_id]

    @pytest.mark.parametrize(
        'route_template',
        ('/api/rentals/{id}', '/web/rentals/{id}'),
    )
    def test_both_update_routes_use_same_final_guard_and_rollback(
        self,
        client,
        db_session,
        route_template,
    ):
        device = Device(name='更新路由冲突设备', is_accessory=False)
        db_session.add(device)
        db_session.flush()
        first = Rental(
            device_id=device.id,
            start_date=date.today() + timedelta(days=1),
            end_date=date.today() + timedelta(days=3),
            customer_name='第一位客户',
            status='not_shipped',
        )
        second = Rental(
            device_id=device.id,
            start_date=date.today() + timedelta(days=5),
            end_date=date.today() + timedelta(days=7),
            customer_name='第二位客户',
            status='not_shipped',
        )
        db_session.add_all([first, second])
        db_session.commit()
        first_id = first.id
        second_id = second.id
        original_start = second.start_date
        original_name = second.customer_name

        response = client.put(
            route_template.format(id=second_id),
            json={
                'start_date': first.end_date.isoformat(),
                'customer_name': '不得提交的新名字',
            },
        )

        assert response.status_code == 409
        assert response.get_json()['data'] == {
            'code': USAGE_PERIOD_CONFLICT,
            'conflicting_rental_ids': [first_id],
        }
        db_session.expire_all()
        persisted = db_session.get(Rental, second_id)
        assert persisted.start_date == original_start
        assert persisted.customer_name == original_name


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
