from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytest

from app import db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental


@dataclass
class ReorderCase:
    first: Rental
    second: Rental
    child: Rental
    first_device: Device
    second_device: Device

    def snapshot(self):
        return [
            (
                rental.id,
                rental.device_id,
                rental.parent_rental_id,
                rental.start_date.isoformat(),
                rental.end_date.isoformat(),
                rental.ship_out_time.isoformat(),
                rental.ship_in_time.isoformat(),
                rental.status,
                rental.destination,
            )
            for rental in Rental.query.order_by(Rental.id).all()
        ]

    def child_snapshot(self):
        child = db.session.get(Rental, self.child.id)
        return (
            child.id,
            child.device_id,
            child.parent_rental_id,
            child.start_date,
            child.end_date,
            child.ship_out_time,
            child.ship_in_time,
            child.status,
            child.destination,
        )

    def main_ids(self):
        return {
            row.id
            for row in Rental.query.filter(
                Rental.parent_rental_id.is_(None)
            ).all()
        }

    def child_ids(self):
        return {
            row.id
            for row in Rental.query.filter(
                Rental.parent_rental_id.isnot(None)
            ).all()
        }

    def add_overlap_pair(self):
        base = date.today() + timedelta(days=20)
        predecessor = Rental(
            device_id=self.first_device.id,
            start_date=base + timedelta(days=1),
            end_date=base + timedelta(days=5),
            ship_out_time=datetime.combine(base, time(19)),
            ship_in_time=datetime.combine(base + timedelta(days=7), time(12)),
            customer_name="王先生",
            customer_phone="13800138000",
            destination="北京市朝阳区",
            status="not_shipped",
        )
        successor = Rental(
            device_id=self.first_device.id,
            start_date=base + timedelta(days=5),
            end_date=base + timedelta(days=9),
            ship_out_time=datetime.combine(base + timedelta(days=6), time(19)),
            ship_in_time=datetime.combine(base + timedelta(days=11), time(12)),
            customer_name="李女士",
            customer_phone="13900139000",
            destination="上海市浦东新区",
            status="not_shipped",
        )
        db.session.add_all([predecessor, successor])
        db.session.commit()
        return predecessor, successor


@pytest.fixture
def seeded_reorder_case(db_session):
    base = date.today() + timedelta(days=5)
    model = DeviceModel(
        name="reorder-api", display_name="重排 API 测试", is_active=True
    )
    db_session.add(model)
    db_session.flush()
    first_device = Device(
        name="R-01",
        model=model.name,
        model_id=model.id,
        is_accessory=False,
        status="online",
        lifecycle_status="active",
    )
    second_device = Device(
        name="R-02",
        model=model.name,
        model_id=model.id,
        is_accessory=False,
        status="online",
        lifecycle_status="active",
    )
    accessory = Device(
        name="手机支架-01",
        model="stand",
        is_accessory=True,
        status="online",
        lifecycle_status="active",
    )
    db_session.add_all([first_device, second_device, accessory])
    db_session.flush()
    first = Rental(
        device_id=first_device.id,
        start_date=base + timedelta(days=1),
        end_date=base + timedelta(days=2),
        ship_out_time=datetime.combine(base, time(19)),
        ship_in_time=datetime.combine(base + timedelta(days=3), time(12)),
        customer_name="客户甲",
        customer_phone="13800000001",
        destination="广州",
        status="not_shipped",
    )
    second = Rental(
        device_id=second_device.id,
        start_date=base + timedelta(days=4),
        end_date=base + timedelta(days=7),
        ship_out_time=datetime.combine(base + timedelta(days=3), time(19)),
        ship_in_time=datetime.combine(base + timedelta(days=8), time(12)),
        customer_name="客户乙",
        customer_phone="13800000002",
        destination="深圳",
        status="not_shipped",
    )
    db_session.add_all([first, second])
    db_session.flush()
    child = Rental(
        device_id=accessory.id,
        parent_rental_id=second.id,
        start_date=second.start_date,
        end_date=second.end_date,
        ship_out_time=second.ship_out_time,
        ship_in_time=second.ship_in_time,
        customer_name=second.customer_name,
        customer_phone=second.customer_phone,
        destination=second.destination,
        status="not_shipped",
    )
    db_session.add(child)
    db_session.commit()
    return ReorderCase(first, second, child, first_device, second_device)
