from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.models.warehouse import Warehouse


@pytest.fixture
def application():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()


def _shipment_facts():
    warehouse = Warehouse(
        name="默认仓库",
        status="active",
        setup_state="ready",
        is_default=True,
        default_slot=1,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试地址 1 号",
    )
    device = Device(name="主设备", warehouse=warehouse)
    rental = Rental(
        device=device,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        customer_name="测试客户",
    )
    db.session.add_all([warehouse, device, rental])
    db.session.flush()
    shipment = OutboundShipment(
        rental=rental,
        origin_warehouse=warehouse,
        origin_warehouse_uuid=warehouse.warehouse_uuid,
        integration_uuid="integration-1",
        provider_account_uuid="account-1",
        integration_secret_revision_uuid="integration-revision-1",
        provider_account_secret_revision_uuid="account-revision-1",
        binding_revision=3,
        account_masked_hint="****1234",
        sender_snapshot={"city": "深圳市"},
        receiver_snapshot={"city": "北京市"},
        cargo_snapshot={
            "items": [{"name": "租赁设备", "count": 1}]
        },
        tracking_check_phone_last4="8000",
        express_type_id=2,
        scheduled_dispatch_at=datetime(2026, 8, 23, 9),
        provider_order_id="tenant-short:shipment-1",
        request_hash="a" * 64,
    )
    db.session.add(shipment)
    db.session.flush()
    return warehouse, rental, shipment


def test_attempt_and_print_job_copy_exact_historical_revisions(application):
    warehouse, rental, shipment = _shipment_facts()
    attempt = ProviderOperationAttempt(
        shipment=shipment,
        operation="create_waybill",
        idempotency_key="shipment-1:create:1",
        attempt_no=1,
        integration_secret_revision_uuid=(
            shipment.integration_secret_revision_uuid
        ),
        provider_account_secret_revision_uuid=(
            shipment.provider_account_secret_revision_uuid
        ),
        binding_revision=shipment.binding_revision,
    )
    print_job = WaybillPrintJob(
        shipment=shipment,
        rental=rental,
        waybill_no_snapshot="SF123456",
        first_label_warehouse_uuid=shipment.origin_warehouse_uuid,
        integration_uuid=shipment.integration_uuid,
        provider_account_uuid=shipment.provider_account_uuid,
        integration_secret_revision_uuid=(
            shipment.integration_secret_revision_uuid
        ),
        provider_account_secret_revision_uuid=(
            shipment.provider_account_secret_revision_uuid
        ),
        binding_revision=shipment.binding_revision,
        return_warehouse=warehouse,
        return_warehouse_uuid=warehouse.warehouse_uuid,
        return_contact_snapshot={"contact": "负责人"},
        printer_sn_snapshot="KM-001",
        operator_user_uuid="user-1",
        idempotency_key="shipment-1:print:1",
    )
    db.session.add_all([attempt, print_job])
    db.session.commit()

    assert attempt.integration_secret_revision_uuid == "integration-revision-1"
    assert print_job.provider_account_secret_revision_uuid == "account-revision-1"
    assert print_job.return_contact_snapshot == {"contact": "负责人"}


def test_provider_order_id_is_unique_and_contains_no_required_pii(application):
    warehouse, _, first = _shipment_facts()
    db.session.commit()
    warehouse_uuid = warehouse.warehouse_uuid
    duplicate_provider_order_id = first.provider_order_id
    device = Device(name="第二台主设备", warehouse=warehouse)
    rental = Rental(
        device=device,
        start_date=date(2026, 9, 5),
        end_date=date(2026, 9, 7),
        customer_name="第二位测试客户",
    )
    duplicate = OutboundShipment(
        rental=rental,
        origin_warehouse=warehouse,
        origin_warehouse_uuid=warehouse_uuid,
        integration_uuid="integration-1",
        provider_account_uuid="account-1",
        integration_secret_revision_uuid="integration-revision-1",
        provider_account_secret_revision_uuid="account-revision-1",
        binding_revision=3,
        account_masked_hint="****1234",
        sender_snapshot={"city": "深圳市"},
        receiver_snapshot={"city": "上海市"},
        cargo_snapshot={
            "items": [{"name": "租赁设备", "count": 1}]
        },
        tracking_check_phone_last4="8001",
        express_type_id=2,
        scheduled_dispatch_at=datetime(2026, 8, 23, 10),
        provider_order_id=duplicate_provider_order_id,
        request_hash="b" * 64,
    )
    db.session.add_all([device, rental, duplicate])

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_invalid_provider_attempt_status_is_rejected(application):
    _, _, shipment = _shipment_facts()
    db.session.add(
        ProviderOperationAttempt(
            shipment=shipment,
            operation="create_waybill",
            idempotency_key="shipment-1:create:1",
            attempt_no=1,
            integration_secret_revision_uuid="integration-revision-1",
            provider_account_secret_revision_uuid="account-revision-1",
            binding_revision=1,
            status="retrying_blindly",
        )
    )

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_provider_attempt_job_intent_provenance_is_all_or_none(application):
    _, _, shipment = _shipment_facts()
    db.session.add(
        ProviderOperationAttempt(
            shipment=shipment,
            operation="create_waybill",
            idempotency_key="shipment-1:create:incomplete-intent",
            attempt_no=1,
            integration_secret_revision_uuid="integration-revision-1",
            provider_account_secret_revision_uuid="account-revision-1",
            binding_revision=1,
            background_job_uuid="11111111-1111-4111-8111-111111111111",
            tenant_access_version=1,
        )
    )

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
