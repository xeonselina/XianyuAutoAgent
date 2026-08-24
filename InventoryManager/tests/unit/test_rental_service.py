"""
租赁服务单元测试 - 配套附件功能
"""

import pytest
from datetime import date, timedelta
from app.models.rental import Rental
from app.models.device import Device
from app.services.rental.rental_service import (
    RentalService,
    RentalUsagePeriodConflictError,
)
from app.services.scheduling import USAGE_PERIOD_CONFLICT


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


class TestRentalServiceFinalUsagePeriodGuard:
    """The final transaction must not trust an optional preview request."""

    def test_create_persists_d33_logistics_facts_and_photo_transfer(
        self,
        app,
        db_session,
    ):
        with app.app_context():
            device = Device(name='物流事实设备', is_accessory=False)
            accessory = Device(name='三脚架-物流事实', is_accessory=True)
            db_session.add_all([device, accessory])
            db_session.commit()
            start_date = date.today() + timedelta(days=10)
            end_date = start_date + timedelta(days=3)

            rental, children = RentalService.create_rental_with_accessories({
                'device_id': device.id,
                'start_date': start_date,
                'end_date': end_date,
                'customer_name': '物流事实客户',
                'logistics_days': 0,
                'photo_transfer': True,
                'accessories': [accessory.id],
            })

            assert rental.logistics_days == 0
            assert rental.planned_ship_out_date == start_date - timedelta(days=1)
            assert rental.planned_return_date == end_date + timedelta(days=1)
            assert rental.photo_transfer is True
            assert len(children) == 1
            assert children[0].logistics_days == 0
            assert children[0].planned_ship_out_date == rental.planned_ship_out_date
            assert children[0].planned_return_date == rental.planned_return_date

    @pytest.mark.parametrize('invalid_value', [None, True, -1, 8, '0'])
    def test_create_rejects_non_d33_logistics_days(
        self,
        app,
        db_session,
        invalid_value,
    ):
        with app.app_context():
            device = Device(name=f'非法物流天数-{invalid_value}', is_accessory=False)
            db_session.add(device)
            db_session.commit()

            with pytest.raises(ValueError, match='logistics_days'):
                RentalService.create_rental_with_accessories({
                    'device_id': device.id,
                    'start_date': date.today() + timedelta(days=10),
                    'end_date': date.today() + timedelta(days=12),
                    'customer_name': '不得创建的客户',
                    'logistics_days': invalid_value,
                    'accessories': [],
                })

            assert Rental.query.count() == 0

    def test_update_recalculates_d33_planned_dates(
        self,
        app,
        db_session,
    ):
        with app.app_context():
            device = Device(name='物流重算设备', is_accessory=False)
            accessory = Device(name='三脚架-物流重算', is_accessory=True)
            db_session.add_all([device, accessory])
            db_session.flush()
            old_start = date.today() + timedelta(days=10)
            old_end = old_start + timedelta(days=2)
            rental = Rental(
                device_id=device.id,
                start_date=old_start,
                end_date=old_end,
                customer_name='物流重算客户',
                status='not_shipped',
                logistics_days=2,
                planned_ship_out_date=old_start - timedelta(days=3),
                planned_return_date=old_end + timedelta(days=3),
            )
            db_session.add(rental)
            db_session.flush()
            child = Rental(
                device_id=accessory.id,
                start_date=old_start,
                end_date=old_end,
                customer_name='物流重算客户',
                status='not_shipped',
                logistics_days=2,
                planned_ship_out_date=old_start - timedelta(days=3),
                planned_return_date=old_end + timedelta(days=3),
                parent_rental_id=rental.id,
            )
            db_session.add(child)
            db_session.commit()
            rental_id = rental.id
            new_start = old_start + timedelta(days=5)
            new_end = old_end + timedelta(days=6)

            updated = RentalService.update_rental_with_accessories(
                rental_id,
                {
                    'start_date': new_start.isoformat(),
                    'end_date': new_end.isoformat(),
                    'logistics_days': 0,
                },
            )

            assert updated.logistics_days == 0
            assert updated.planned_ship_out_date == new_start - timedelta(days=1)
            assert updated.planned_return_date == new_end + timedelta(days=1)
            assert child.start_date == new_start
            assert child.end_date == new_end
            assert child.logistics_days == 0
            assert child.planned_ship_out_date == updated.planned_ship_out_date
            assert child.planned_return_date == updated.planned_return_date

            later_end = new_end + timedelta(days=2)
            updated = RentalService.update_rental_with_accessories(
                rental_id,
                {'end_date': later_end.isoformat()},
            )
            assert updated.logistics_days == 0
            assert updated.planned_ship_out_date == new_start - timedelta(days=1)
            assert updated.planned_return_date == later_end + timedelta(days=1)
            assert child.end_date == later_end
            assert child.planned_return_date == updated.planned_return_date

            with pytest.raises(ValueError, match='附件租赁'):
                RentalService.update_rental_status(child.id, 'shipped')
            db_session.refresh(child)
            assert child.status == 'not_shipped'

    def test_status_events_sync_legacy_and_actual_timestamps(
        self,
        app,
        db_session,
    ):
        with app.app_context():
            device = Device(name='物流事件设备', is_accessory=False)
            accessory = Device(name='三脚架-物流事件', is_accessory=True)
            db_session.add_all([device, accessory])
            db_session.commit()
            rental, children = RentalService.create_rental_with_accessories({
                'device_id': device.id,
                'start_date': date.today() + timedelta(days=10),
                'end_date': date.today() + timedelta(days=12),
                'customer_name': '物流事件客户',
                'logistics_days': 1,
                'accessories': [accessory.id],
            })

            shipped = RentalService.update_rental_status(rental.id, 'shipped')
            assert shipped.actual_shipped_at == shipped.ship_out_time
            assert shipped.actual_shipped_at is not None
            assert children[0].actual_shipped_at == children[0].ship_out_time
            assert children[0].actual_shipped_at is not None

            returned = RentalService.update_rental_status(rental.id, 'returned')
            assert returned.actual_returned_at == returned.ship_in_time
            assert returned.actual_returned_at is not None
            assert children[0].actual_returned_at == children[0].ship_in_time
            assert children[0].actual_returned_at is not None

    def test_create_rejects_inclusive_overlap_without_logistics_times(
        self,
        app,
        db_session,
    ):
        with app.app_context():
            device = Device(name='冲突设备', is_accessory=False)
            db_session.add(device)
            db_session.flush()
            existing = Rental(
                device_id=device.id,
                start_date=date.today() + timedelta(days=2),
                end_date=date.today() + timedelta(days=4),
                customer_name='原客户',
                status='not_shipped',
            )
            db_session.add(existing)
            db_session.commit()
            existing_id = existing.id

            # The boundary day is inclusive.  No ship_out/ship_in values are
            # supplied, proving the legacy preview contract cannot be used as
            # the final-write authority.
            with pytest.raises(RentalUsagePeriodConflictError) as captured:
                RentalService.create_rental_with_accessories({
                    'device_id': device.id,
                    'start_date': date.today() + timedelta(days=4),
                    'end_date': date.today() + timedelta(days=6),
                    'customer_name': '不得写入的客户',
                    'includes_handle': True,
                    'accessories': [],
                })

            assert captured.value.code == USAGE_PERIOD_CONFLICT
            assert str(captured.value) == USAGE_PERIOD_CONFLICT
            assert captured.value.conflicting_rental_ids == (existing_id,)
            assert '原客户' not in str(captured.value)
            assert '不得写入的客户' not in str(captured.value)
            db_session.expire_all()
            rows = Rental.query.order_by(Rental.id).all()
            assert [row.id for row in rows] == [existing_id]

    def test_update_conflict_rolls_back_all_requested_changes(
        self,
        app,
        db_session,
    ):
        with app.app_context():
            device = Device(name='更新冲突设备', is_accessory=False)
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
                includes_handle=False,
                status='not_shipped',
            )
            db_session.add_all([first, second])
            db_session.commit()
            first_id = first.id
            second_id = second.id
            original_start = second.start_date
            original_end = second.end_date

            with pytest.raises(RentalUsagePeriodConflictError) as captured:
                RentalService.update_rental_with_accessories(
                    second_id,
                    {
                        'start_date': first.end_date.isoformat(),
                        'end_date': (
                            first.end_date + timedelta(days=2)
                        ).isoformat(),
                        'customer_name': '不得提交的新名字',
                        'includes_handle': True,
                    },
                )

            assert captured.value.conflicting_rental_ids == (first_id,)
            db_session.expire_all()
            persisted = db_session.get(Rental, second_id)
            assert persisted.start_date == original_start
            assert persisted.end_date == original_end
            assert persisted.customer_name == '第二位客户'
            assert persisted.includes_handle is False

    def test_adjacent_customer_period_is_allowed(self, app, db_session):
        with app.app_context():
            device = Device(name='相邻档期设备', is_accessory=False)
            db_session.add(device)
            db_session.flush()
            existing = Rental(
                device_id=device.id,
                start_date=date.today() + timedelta(days=1),
                end_date=date.today() + timedelta(days=3),
                customer_name='前一位客户',
                status='not_shipped',
            )
            db_session.add(existing)
            db_session.commit()

            created, _children = RentalService.create_rental_with_accessories({
                'device_id': device.id,
                'start_date': date.today() + timedelta(days=4),
                'end_date': date.today() + timedelta(days=6),
                'customer_name': '后一位客户',
                'accessories': [],
            })

            assert created.id is not None
            assert Rental.query.count() == 2


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
