from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from app import create_app, db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.models.warehouse import (
    Warehouse,
    WarehousePrinter,
    WarehouseProviderBinding,
)
from app.services.shipping_execution_service import (
    PrintLabelKind,
    PrintOutcome,
    ProviderOutcome,
    ShippingExecutionService,
    ShippingAccessoryUnfulfilledError,
    ShippingIdempotencyConflictError,
    ShippingInputError,
    ShippingPrinterUnavailableError,
    ShippingSnapshotMismatchError,
    ShippingStateConflictError,
    ShippingTransactionRequiredError,
    ShippingUnknownOutcomeError,
    ShippingJobProvenance,
    UnknownResolution,
)
from inventory_control.integrations import SfProviderExecutionContext


INTEGRATION_UUID = "11111111-1111-4111-8111-111111111111"
ACCOUNT_UUID = "22222222-2222-4222-8222-222222222222"
INTEGRATION_REVISION_UUID = "33333333-3333-4333-8333-333333333333"
ACCOUNT_REVISION_UUID = "44444444-4444-4444-8444-444444444444"
OPERATOR_UUID = "55555555-5555-4555-8555-555555555555"
BACKGROUND_JOB_UUID = "66666666-6666-4666-8666-666666666666"
SHIPMENT_UUID = "77777777-7777-4777-8777-777777777777"
TENANT_UUID = "99999999-9999-4999-8999-999999999999"
NOW = datetime(2026, 8, 22, 9, 0, 0)


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


@pytest.fixture
def session(application):
    return db.session()


def seed_inventory(session):
    with session.begin():
        warehouse = Warehouse(
            name="测试仓",
            status="active",
            setup_state="ready",
            is_default=True,
            default_slot=1,
            contact_name="仓库联系人",
            contact_phone="13800138000",
            province="测试省",
            city="测试市",
            district="测试区",
            address_detail="测试路 1 号",
        )
        device = Device(name="主设备", warehouse=warehouse)
        rental = Rental(
            device=device,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            customer_name="测试客户",
            customer_phone="13900139000",
            customer_province="客户省",
            customer_city="客户市",
            customer_district="客户区",
            customer_address_detail="客户路 2 号",
        )
        session.add_all((warehouse, device, rental))
        session.flush()
        session.add(
            WarehousePrinter(
                warehouse_id=warehouse.id,
                printer_sn="KM-PRINTER-001",
                display_name="测试打印机",
                provider="kuaimai",
                status="active",
                last_verified_at=NOW,
            )
        )
        session.add(
            WarehouseProviderBinding(
                warehouse_id=warehouse.id,
                provider="sf",
                provider_account_uuid=ACCOUNT_UUID,
                binding_revision=7,
                status="active",
                verified_at=NOW,
                bound_by=OPERATOR_UUID,
            )
        )
        facts = {
            "warehouse_id": warehouse.id,
            "warehouse_uuid": warehouse.warehouse_uuid,
            "device_id": device.id,
            "rental_id": rental.id,
        }
    return facts


def add_unfulfilled_accessory_request(session, facts):
    with session.begin():
        accessory_type = AccessoryType(
            name="tripod",
            display_name="三脚架",
            tracking_mode="logical_unit",
        )
        session.add(accessory_type)
        session.flush()
        accessory_type_id = accessory_type.id
        session.add(
            RentalAccessoryRequest(
                rental_id=facts["rental_id"],
                accessory_type_id=accessory_type_id,
                name_snapshot=accessory_type.display_name,
            )
        )
    return accessory_type_id


def add_linked_accessory_request(
    session,
    facts,
    *,
    condition_status="active",
    warehouse_id=None,
):
    with session.begin():
        accessory_type = AccessoryType(
            name="tripod",
            display_name="三脚架",
            tracking_mode="logical_unit",
        )
        unit = AccessoryUnit(
            accessory_type=accessory_type,
            warehouse_id=warehouse_id or facts["warehouse_id"],
            condition_status=condition_status,
        )
        session.add_all((accessory_type, unit))
        session.flush()
        session.add_all(
            (
                RentalAccessoryRequest(
                    rental_id=facts["rental_id"],
                    accessory_type_id=accessory_type.id,
                    name_snapshot=accessory_type.display_name,
                ),
                RentalAccessoryUnitLink(
                    rental_id=facts["rental_id"],
                    accessory_type_id=accessory_type.id,
                    accessory_unit_id=unit.id,
                    reservation_start_at=datetime(2026, 8, 31, 8),
                    reservation_end_at=datetime(2026, 9, 5, 8),
                ),
            )
        )


def shipment_command(facts, **changes):
    context_changes = changes.pop("provider_context_changes", {})
    context_values = {
        "tenant_uuid": TENANT_UUID,
        "warehouse_uuid": facts["warehouse_uuid"],
        "provider_account_uuid": ACCOUNT_UUID,
        "integration_uuid": INTEGRATION_UUID,
        "integration_secret_revision_uuid": INTEGRATION_REVISION_UUID,
        "provider_account_secret_revision_uuid": ACCOUNT_REVISION_UUID,
        "global_claim_uuid": "88888888-8888-4888-8888-888888888888",
        "claim_generation": 3,
        "binding_revision": 7,
        "masked_account_hint": "****1234",
    }
    context_values.update(context_changes)
    provider_context = SfProviderExecutionContext(**context_values)
    command = {
        "shipment_uuid": SHIPMENT_UUID,
        "rental_id": facts["rental_id"],
        "device_id": facts["device_id"],
        "provider_context": provider_context,
        "receiver_snapshot": {
            "contact_name": "测试客户",
            "contact_phone": "13900139000",
            "province": "客户省",
            "city": "客户市",
            "district": "客户区",
            "address_detail": "客户路 2 号",
        },
        "express_type_id": 2,
        "scheduled_dispatch_at": datetime(
            2026, 9, 1, 9, 0, tzinfo=timezone.utc
        ),
    }
    command.update(changes)
    return command


def prepare_shipment(session, facts):
    with session.begin():
        result = ShippingExecutionService(session).prepare_shipment(
            **shipment_command(facts)
        )
    return result


def submit_shipment(session, facts):
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)
    with session.begin():
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:shipment-0001:attempt-1",
            background_job_uuid=BACKGROUND_JOB_UUID,
        )
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
    with session.begin():
        service.record_provider_result(
            attempt_id=attempt.attempt_id,
            expected_status="provider_submitting",
            outcome=ProviderOutcome.SUCCESS,
            finished_at=NOW,
            waybill_no="SF1234567890",
            response_hash="a" * 64,
            latency_ms=123,
        )
    return shipment.shipment_id


def print_command(facts, shipment_id, **changes):
    command = {
        "shipment_id": shipment_id,
        "rental_id": facts["rental_id"],
        "first_label_warehouse_uuid": facts["warehouse_uuid"],
        "return_warehouse_id": facts["warehouse_id"],
        "return_warehouse_uuid": facts["warehouse_uuid"],
        "return_contact_snapshot": {
            "order_no": "ORDER-1",
            "due_return_date": "2026-09-04",
            "contact_name": "仓库联系人",
            "contact_phone": "13800138000",
            "address": "测试路 1 号",
            "customer_visible_note": "请妥善包装",
            "tutorial_qr_codes": ["install", "transfer"],
        },
        "operator_user_uuid": OPERATOR_UUID,
        "idempotency_key": "print:shipment-0001",
    }
    command.update(changes)
    return command


def prepare_print_pair(session, facts, shipment_id):
    with session.begin():
        return ShippingExecutionService(session).prepare_paired_print_jobs(
            **print_command(facts, shipment_id)
        )


def test_prepare_shipment_requires_explicit_caller_transaction(session):
    facts = seed_inventory(session)

    with pytest.raises(ShippingTransactionRequiredError):
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(facts)
        )


def test_prepare_shipment_snapshots_exact_facts_hash_and_idempotent_replay(
    session,
):
    facts = seed_inventory(session)
    service = ShippingExecutionService(session)

    with session.begin():
        created = service.prepare_shipment(**shipment_command(facts))
        replay = service.prepare_shipment(**shipment_command(facts))
        persisted = session.get(OutboundShipment, created.shipment_id)

        assert replay.shipment_id == created.shipment_id
        assert replay.idempotent_replay is True
        assert len(created.request_hash) == 64
        assert persisted.request_hash == created.request_hash
        assert persisted.id == SHIPMENT_UUID
        assert persisted.provider_order_id == f"sf:{TENANT_UUID}:{SHIPMENT_UUID}"
        assert "测试客户" not in persisted.provider_order_id
        assert persisted.rental_id == facts["rental_id"]
        assert persisted.origin_warehouse_id == facts["warehouse_id"]
        assert persisted.origin_warehouse_uuid == facts["warehouse_uuid"]
        assert persisted.integration_uuid == INTEGRATION_UUID
        assert persisted.provider_account_uuid == ACCOUNT_UUID
        assert (
            persisted.integration_secret_revision_uuid
            == INTEGRATION_REVISION_UUID
        )
        assert (
            persisted.provider_account_secret_revision_uuid
            == ACCOUNT_REVISION_UUID
        )
        assert persisted.sender_snapshot == {
            "contact_name": "仓库联系人",
            "contact_phone": "13800138000",
            "province": "测试省",
            "city": "测试市",
            "district": "测试区",
            "address_detail": "测试路 1 号",
        }
        assert persisted.receiver_snapshot["contact_name"] == "测试客户"


def test_prepare_shipment_rejects_same_provider_identity_with_changed_snapshot(
    session,
):
    facts = seed_inventory(session)
    service = ShippingExecutionService(session)

    with session.begin(), pytest.raises(ShippingIdempotencyConflictError):
        service.prepare_shipment(**shipment_command(facts))
        service.prepare_shipment(
            **shipment_command(
                facts,
                receiver_snapshot={
                    "contact": "另一客户",
                    "phone": "13900139000",
                },
            )
        )


def test_prepare_shipment_rejects_same_identity_with_changed_dispatch_time(
    session,
):
    facts = seed_inventory(session)
    service = ShippingExecutionService(session)

    with session.begin():
        service.prepare_shipment(**shipment_command(facts))

    with session.begin(), pytest.raises(ShippingIdempotencyConflictError):
        service.prepare_shipment(
            **shipment_command(
                facts,
                scheduled_dispatch_at=datetime(
                    2026,
                    9,
                    1,
                    10,
                    0,
                    tzinfo=timezone.utc,
                ),
            )
        )


def test_prepare_shipment_requires_timezone_aware_dispatch_time(session):
    facts = seed_inventory(session)

    with session.begin(), pytest.raises(ShippingInputError):
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(
                facts,
                scheduled_dispatch_at=datetime(2026, 9, 1, 9, 0),
            )
        )


def test_prepare_shipment_rejects_new_shipment_for_relay_successor(session):
    facts = seed_inventory(session)
    with session.begin():
        successor = session.get(Rental, facts["rental_id"])
        predecessor = Rental(
            device_id=successor.device_id,
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 24),
            customer_name="接力前单",
        )
        session.add(predecessor)
        session.flush()
        session.add(
            RentalRelayBinding(
                predecessor_rental_id=predecessor.id,
                successor_rental_id=successor.id,
                confirmed_at=NOW,
            )
        )

    with session.begin(), pytest.raises(ShippingStateConflictError):
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(facts)
        )


def test_prepare_shipment_rejects_stale_device_warehouse_snapshot(session):
    facts = seed_inventory(session)
    service = ShippingExecutionService(session)

    with session.begin():
        other = Warehouse(
            name="另一个仓",
            status="active",
            setup_state="ready",
            is_default=False,
            contact_name="联系人",
            contact_phone="13800138001",
            province="省",
            city="市",
            district="区",
            address_detail="路 2 号",
        )
        session.add(other)
        session.flush()
        device = session.get(Device, facts["device_id"])
        device.warehouse_id = other.id

    with session.begin(), pytest.raises(ShippingSnapshotMismatchError):
        service.prepare_shipment(**shipment_command(facts))


def test_prepare_shipment_rejects_control_context_local_binding_drift(session):
    facts = seed_inventory(session)

    with session.begin(), pytest.raises(ShippingSnapshotMismatchError):
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(
                facts,
                provider_context_changes={"binding_revision": 8},
            )
        )

    assert session.scalars(select(OutboundShipment)).all() == []


def test_prepare_shipment_blocks_request_without_same_type_unit_link(session):
    facts = seed_inventory(session)
    add_unfulfilled_accessory_request(session, facts)

    with session.begin(), pytest.raises(ShippingAccessoryUnfulfilledError) as caught:
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(facts)
        )

    assert caught.value.code == "SHIPPING_ACCESSORY_UNFULFILLED"
    assert session.execute(select(OutboundShipment)).scalars().all() == []


def test_prepare_shipment_accepts_active_eligible_linked_unit(session):
    facts = seed_inventory(session)
    add_linked_accessory_request(session, facts)

    shipment = prepare_shipment(session, facts)
    assert shipment.status == "prepared"


def test_prepare_shipment_rejects_inactive_linked_unit(session):
    facts = seed_inventory(session)
    add_linked_accessory_request(
        session,
        facts,
        condition_status="lost",
    )
    with session.begin(), pytest.raises(ShippingAccessoryUnfulfilledError):
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(
                facts,
                shipment_uuid="a1111111-1111-4111-8111-111111111111",
            )
        )


def test_prepare_shipment_rejects_active_linked_unit_from_another_warehouse(
    session,
):
    facts = seed_inventory(session)
    with session.begin():
        other = Warehouse(
            name="异地仓",
            status="active",
            setup_state="ready",
            is_default=False,
            contact_name="异地联系人",
            contact_phone="13800138001",
            province="异地省",
            city="异地市",
            district="异地区",
            address_detail="异地路 2 号",
        )
        session.add(other)
        session.flush()
        other_warehouse_id = other.id
    add_linked_accessory_request(
        session,
        facts,
        warehouse_id=other_warehouse_id,
    )

    with session.begin(), pytest.raises(ShippingAccessoryUnfulfilledError):
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(
                facts,
                shipment_uuid="b2222222-2222-4222-8222-222222222222",
            )
        )


def test_waybill_submission_rechecks_accessory_facts_at_effect_boundary(session):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)
    with session.begin():
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:accessory-boundary",
        )
    add_unfulfilled_accessory_request(session, facts)

    with session.begin(), pytest.raises(ShippingAccessoryUnfulfilledError):
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )

    assert session.get(ProviderOperationAttempt, attempt.attempt_id).status == (
        "prepared"
    )
    assert session.get(OutboundShipment, shipment.shipment_id).status == "prepared"


def test_waybill_submission_rechecks_current_device_warehouse(session):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)
    with session.begin():
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:warehouse-boundary",
        )
        other = Warehouse(
            name="调仓后仓库",
            status="active",
            setup_state="ready",
            is_default=False,
            contact_name="调仓联系人",
            contact_phone="13800138002",
            province="调仓省",
            city="调仓市",
            district="调仓区",
            address_detail="调仓路 3 号",
        )
        session.add(other)
        session.flush()
        session.get(Device, facts["device_id"]).warehouse_id = other.id

    with session.begin(), pytest.raises(ShippingSnapshotMismatchError):
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )

    assert session.get(ProviderOperationAttempt, attempt.attempt_id).status == (
        "prepared"
    )
    assert session.get(OutboundShipment, shipment.shipment_id).status == "prepared"


def test_new_warehouse_shipment_waits_for_confirmed_old_waybill_cancellation(
    session,
):
    facts = seed_inventory(session)
    old_shipment_id = submit_shipment(session, facts)
    new_account = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    new_account_revision = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    with session.begin():
        warehouse = Warehouse(
            name="调仓后仓库",
            status="active",
            setup_state="ready",
            is_default=False,
            contact_name="新仓联系人",
            contact_phone="13800138002",
            province="浙江省",
            city="杭州市",
            district="余杭区",
            address_detail="新仓路 3 号",
        )
        session.add(warehouse)
        session.flush()
        session.add(
            WarehouseProviderBinding(
                warehouse_id=warehouse.id,
                provider="sf",
                provider_account_uuid=new_account,
                binding_revision=1,
                status="active",
                verified_at=NOW,
                bound_by=OPERATOR_UUID,
            )
        )
        session.get(Device, facts["device_id"]).warehouse_id = warehouse.id
        new_warehouse_uuid = warehouse.warehouse_uuid

    new_context = {
        "warehouse_uuid": new_warehouse_uuid,
        "provider_account_uuid": new_account,
        "provider_account_secret_revision_uuid": new_account_revision,
        "binding_revision": 1,
        "masked_account_hint": "****5678",
    }
    new_command = shipment_command(
        facts,
        provider_context_changes=new_context,
        shipment_uuid="c3333333-3333-4333-8333-333333333333",
    )
    service = ShippingExecutionService(session)
    with session.begin(), pytest.raises(ShippingStateConflictError):
        service.prepare_shipment(**new_command)

    with session.begin():
        service.request_cancellation(
            shipment_id=old_shipment_id,
            expected_status="submitted",
            requested_at=NOW,
        )
        attempt = service.prepare_provider_attempt(
            shipment_id=old_shipment_id,
            operation="cancel_waybill",
            idempotency_key="sf:cancel:after-device-move",
        )
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
        service.record_provider_result(
            attempt_id=attempt.attempt_id,
            expected_status="provider_submitting",
            outcome=ProviderOutcome.UNKNOWN,
            finished_at=NOW,
            safe_provider_code="CANCEL_RESULT_UNKNOWN",
        )

    with session.begin(), pytest.raises(ShippingUnknownOutcomeError):
        service.prepare_shipment(**new_command)
    with session.begin():
        service.reconcile_unknown_provider_attempt(
            attempt_id=attempt.attempt_id,
            resolution=UnknownResolution.CONFIRMED_SUCCESS,
            reconciled_at=NOW,
            safe_provider_code="CANCEL_CONFIRMED",
        )
        replacement = service.prepare_shipment(**new_command)

    assert replacement.status == "prepared"
    with session.begin():
        old = session.get(OutboundShipment, old_shipment_id)
        new = session.get(OutboundShipment, replacement.shipment_id)
        assert old.status == "cancelled"
        assert new.origin_warehouse_uuid == new_warehouse_uuid
        assert new.provider_account_uuid == new_account
        assert new.sender_snapshot["city"] == "杭州市"


def test_print_submission_rechecks_accessory_facts_at_effect_boundary(session):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    pair = prepare_print_pair(session, facts, shipment_id)
    add_unfulfilled_accessory_request(session, facts)
    service = ShippingExecutionService(session)

    with session.begin(), pytest.raises(ShippingAccessoryUnfulfilledError):
        service.mark_print_submitting(
            print_job_id=pair.first_label.print_job_id,
            label_kind=PrintLabelKind.FIRST,
            expected_status="prepared",
            submitted_at=NOW,
        )

    assert session.get(
        WaybillPrintJob,
        pair.first_label.print_job_id,
    ).status == "prepared"


@pytest.mark.parametrize(
    "change",
    [
        {"provider_context_changes": {"binding_revision": 0}},
        {"receiver_snapshot": {"phone": "bad"}},
        {
            "provider_context_changes": {
                "masked_account_hint": "unmasked-account"
            }
        },
        {"shipment_uuid": "客户姓名"},
        {"receiver_snapshot": {"bad": float("nan")}},
        {
            "provider_context_changes": {
                "integration_secret_revision_uuid": "secret-not-a-uuid"
            }
        },
    ],
)
def test_shipment_input_errors_are_stable_and_do_not_echo_values(session, change):
    facts = seed_inventory(session)
    with session.begin(), pytest.raises(ShippingInputError) as caught:
        ShippingExecutionService(session).prepare_shipment(
            **shipment_command(facts, **change)
        )

    assert caught.value.code == "SHIPPING_INPUT_INVALID"
    rendered = f"{caught.value!s} {caught.value!r}"
    assert "客户姓名" not in rendered
    assert "secret-not-a-uuid" not in rendered
    assert "unmasked-account" not in rendered


def test_attempt_copies_exact_revisions_sequences_and_global_key(session):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin():
        first = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:one",
            background_job_uuid=BACKGROUND_JOB_UUID,
        )
        replay = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:one",
            background_job_uuid=BACKGROUND_JOB_UUID,
        )
        row = session.get(ProviderOperationAttempt, first.attempt_id)
        assert replay.attempt_id == first.attempt_id
        assert replay.idempotent_replay is True
        assert first.attempt_no == 1
        assert row.integration_secret_revision_uuid == INTEGRATION_REVISION_UUID
        assert row.provider_account_secret_revision_uuid == ACCOUNT_REVISION_UUID
        assert row.binding_revision == 7

        service.mark_provider_submitting(
            attempt_id=first.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
        service.record_provider_result(
            attempt_id=first.attempt_id,
            expected_status="provider_submitting",
            outcome="definitive_failure",
            finished_at=NOW,
            safe_provider_code="SF_REJECTED",
            response_hash="b" * 64,
        )
        second = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:two",
        )
        assert second.attempt_no == 2

        with pytest.raises(ShippingIdempotencyConflictError):
            service.prepare_provider_attempt(
                shipment_id=shipment.shipment_id,
                operation="cancel_waybill",
                idempotency_key="sf:create:two",
            )


def test_attempt_persists_immutable_job_provenance_for_later_enqueue(session):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)
    provenance = ShippingJobProvenance(
        job_uuid=BACKGROUND_JOB_UUID,
        tenant_access_version=7,
        requested_by_user_uuid=OPERATOR_UUID,
        request_id="request-create-waybill-1",
        correlation_id="correlation-create-waybill-1",
    )

    with session.begin():
        first = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:durable-intent",
            job_provenance=provenance,
        )
        replay = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:durable-intent",
            background_job_uuid=BACKGROUND_JOB_UUID,
            job_provenance=provenance,
        )
        row = session.get(ProviderOperationAttempt, first.attempt_id)

        assert replay.idempotent_replay is True
        assert row.background_job_uuid == BACKGROUND_JOB_UUID
        assert row.tenant_access_version == 7
        assert row.requested_by_user_uuid == OPERATOR_UUID
        assert row.request_id == "request-create-waybill-1"
        assert row.correlation_id == "correlation-create-waybill-1"
        assert row.job_enqueued_at is None

        acknowledged = service.acknowledge_provider_job_enqueued(
            attempt_id=first.attempt_id,
            shipment_id=shipment.shipment_id,
            provenance=provenance,
            enqueued_at=NOW,
        )
        replayed_ack = service.acknowledge_provider_job_enqueued(
            attempt_id=first.attempt_id,
            shipment_id=shipment.shipment_id,
            provenance=provenance,
            enqueued_at=NOW,
        )
        assert acknowledged is True
        assert replayed_ack is False
        assert row.job_enqueued_at == NOW

        changed = ShippingJobProvenance(
            job_uuid=BACKGROUND_JOB_UUID,
            tenant_access_version=8,
            requested_by_user_uuid=OPERATOR_UUID,
            request_id="request-create-waybill-1",
            correlation_id="correlation-create-waybill-1",
        )
        with pytest.raises(ShippingIdempotencyConflictError):
            service.prepare_provider_attempt(
                shipment_id=shipment.shipment_id,
                operation="create_waybill",
                idempotency_key="sf:create:durable-intent",
                job_provenance=changed,
            )
        with pytest.raises(ShippingIdempotencyConflictError):
            service.acknowledge_provider_job_enqueued(
                attempt_id=first.attempt_id,
                shipment_id=shipment.shipment_id,
                provenance=changed,
                enqueued_at=NOW,
            )


def test_shipping_job_provenance_rejects_invalid_identity_values():
    with pytest.raises(ShippingInputError):
        ShippingJobProvenance(
            job_uuid="not-a-uuid",
            tenant_access_version=1,
            requested_by_user_uuid=OPERATOR_UUID,
            request_id="request-1",
        )
    with pytest.raises(ShippingInputError):
        ShippingJobProvenance(
            job_uuid=BACKGROUND_JOB_UUID,
            tenant_access_version=0,
            requested_by_user_uuid=OPERATOR_UUID,
            request_id="request-1",
        )


def test_create_attempt_cas_success_sets_waybill_and_rejects_stale_transition(
    session,
):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin():
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:success",
        )
        submitting = service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
        assert submitting.status == "provider_submitting"

    with session.begin():
        completed = service.record_provider_result(
            attempt_id=attempt.attempt_id,
            expected_status="provider_submitting",
            outcome="success",
            finished_at=NOW,
            waybill_no="SF00000001",
            response_hash="c" * 64,
            latency_ms=5,
        )
        persisted = session.get(OutboundShipment, shipment.shipment_id)
        assert completed.status == "succeeded"
        assert persisted.status == "submitted"
        assert persisted.waybill_no == "SF00000001"

    with session.begin(), pytest.raises(ShippingStateConflictError):
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )


def test_unknown_create_blocks_blind_retry_until_explicit_reconciliation(session):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin():
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:unknown",
        )
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
    with session.begin():
        result = service.record_provider_result(
            attempt_id=attempt.attempt_id,
            expected_status="provider_submitting",
            outcome=ProviderOutcome.UNKNOWN,
            finished_at=NOW,
        )
        assert result.status == "unknown"
        assert session.get(
            OutboundShipment,
            shipment.shipment_id,
        ).status == "needs_review"

    with session.begin(), pytest.raises(ShippingUnknownOutcomeError):
        service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:blind-retry",
        )

    with session.begin():
        reconciled = service.reconcile_unknown_provider_attempt(
            attempt_id=attempt.attempt_id,
            resolution=UnknownResolution.CONFIRMED_NO_EFFECT,
            reconciled_at=NOW,
            safe_provider_code="RECONCILED_NOT_SUBMITTED",
        )
        assert reconciled.status == "definitive_failure"
        assert session.get(OutboundShipment, shipment.shipment_id).status == "failed"
        retry = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:after-reconcile",
        )
        assert retry.attempt_no == 2


def test_unknown_query_claim_is_one_shot_before_provider_query(session):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin():
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:query-claim",
        )
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
    with session.begin():
        service.record_provider_result(
            attempt_id=attempt.attempt_id,
            expected_status="provider_submitting",
            outcome=ProviderOutcome.UNKNOWN,
            finished_at=NOW,
        )
    with session.begin():
        claimed = service.begin_unknown_provider_reconciliation(
            attempt_id=attempt.attempt_id,
            started_at=NOW,
        )
        assert claimed.status == "needs_review"
        assert session.get(OutboundShipment, shipment.shipment_id).status == (
            "needs_review"
        )
    with session.begin(), pytest.raises(ShippingUnknownOutcomeError):
        service.begin_unknown_provider_reconciliation(
            attempt_id=attempt.attempt_id,
            started_at=NOW,
        )


def test_crash_after_submit_can_be_claimed_and_reconciled_success(session):
    facts = seed_inventory(session)
    shipment = prepare_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin():
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment.shipment_id,
            operation="create_waybill",
            idempotency_key="sf:create:crash-after-submit",
        )
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
    with session.begin():
        claimed = service.begin_unknown_provider_reconciliation(
            attempt_id=attempt.attempt_id,
            started_at=NOW,
        )
        assert claimed.status == "needs_review"
        assert session.get(OutboundShipment, shipment.shipment_id).status == (
            "needs_review"
        )
    with session.begin():
        reconciled = service.reconcile_unknown_provider_attempt(
            attempt_id=attempt.attempt_id,
            resolution=UnknownResolution.CONFIRMED_SUCCESS,
            reconciled_at=NOW,
            safe_provider_code="SF_QUERY_CONFIRMED",
            waybill_no="SF00000002",
            response_hash="d" * 64,
        )
        assert reconciled.status == "succeeded"
        persisted = session.get(OutboundShipment, shipment.shipment_id)
        assert persisted.status == "submitted"
        assert persisted.waybill_no == "SF00000002"


@pytest.mark.parametrize(
    ("outcome", "shipment_status", "attempt_status"),
    [
        (ProviderOutcome.SUCCESS, "cancelled", "succeeded"),
        (ProviderOutcome.DEFINITIVE_FAILURE, "submitted", "definitive_failure"),
        (ProviderOutcome.UNKNOWN, "cancel_unknown", "unknown"),
    ],
)
def test_cancellation_requested_success_failure_and_unknown(
    session,
    outcome,
    shipment_status,
    attempt_status,
):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin():
        requested = service.request_cancellation(
            shipment_id=shipment_id,
            expected_status="submitted",
            requested_at=NOW,
        )
        assert requested.status == "cancel_requested"
        replay = service.request_cancellation(
            shipment_id=shipment_id,
            expected_status="submitted",
            requested_at=NOW,
        )
        assert replay.idempotent_replay is True
        attempt = service.prepare_provider_attempt(
            shipment_id=shipment_id,
            operation="cancel_waybill",
            idempotency_key=f"sf:cancel:{outcome.value}",
        )
        service.mark_provider_submitting(
            attempt_id=attempt.attempt_id,
            expected_status="prepared",
            started_at=NOW,
        )
    with session.begin():
        result = service.record_provider_result(
            attempt_id=attempt.attempt_id,
            expected_status="provider_submitting",
            outcome=outcome,
            finished_at=NOW,
            safe_provider_code=(
                None if outcome is ProviderOutcome.SUCCESS else "SF_CANCEL_RESULT"
            ),
        )
        assert result.status == attempt_status
        assert session.get(OutboundShipment, shipment_id).status == shipment_status

    if outcome is ProviderOutcome.UNKNOWN:
        with session.begin(), pytest.raises(ShippingUnknownOutcomeError):
            service.prepare_provider_attempt(
                shipment_id=shipment_id,
                operation="cancel_waybill",
                idempotency_key="sf:cancel:blind-retry",
            )
        with session.begin():
            service.reconcile_unknown_provider_attempt(
                attempt_id=attempt.attempt_id,
                resolution="confirmed_no_effect",
                reconciled_at=NOW,
                safe_provider_code="CANCEL_NOT_APPLIED",
            )
            assert session.get(OutboundShipment, shipment_id).status == "submitted"


def test_prepare_paired_print_jobs_copies_exact_two_label_context_and_replays(
    session,
):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin():
        created = service.prepare_paired_print_jobs(
            **print_command(facts, shipment_id)
        )
        replay = service.prepare_paired_print_jobs(
            **print_command(facts, shipment_id)
        )
        rows = tuple(
            session.execute(
                select(WaybillPrintJob).order_by(WaybillPrintJob.idempotency_key)
            )
            .scalars()
            .all()
        )

        assert created.first_label.print_job_id != created.second_label.print_job_id
        assert replay.idempotent_replay is True
        assert replay.first_label.print_job_id == created.first_label.print_job_id
        assert len(rows) == 2
        assert {row.idempotency_key for row in rows} == {
            "print:shipment-0001:first",
            "print:shipment-0001:second",
        }
        for row in rows:
            assert row.waybill_no_snapshot == "SF1234567890"
            assert row.first_label_warehouse_uuid == facts["warehouse_uuid"]
            assert row.return_warehouse_uuid == facts["warehouse_uuid"]
            assert row.integration_uuid == INTEGRATION_UUID
            assert row.provider_account_uuid == ACCOUNT_UUID
            assert row.integration_secret_revision_uuid == INTEGRATION_REVISION_UUID
            assert row.provider_account_secret_revision_uuid == ACCOUNT_REVISION_UUID
            assert row.binding_revision == 7
            assert row.printer_sn_snapshot == "KM-PRINTER-001"
            assert row.return_contact_snapshot["order_no"] == "ORDER-1"


def test_print_idempotency_key_rejects_changed_exact_snapshot(session):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    service = ShippingExecutionService(session)

    with session.begin(), pytest.raises(ShippingIdempotencyConflictError):
        service.prepare_paired_print_jobs(**print_command(facts, shipment_id))
        service.prepare_paired_print_jobs(
            **print_command(
                facts,
                shipment_id,
                return_contact_snapshot={"order_no": "CHANGED"},
            )
        )


@pytest.mark.parametrize("printer_state", ["missing", "inactive", "failed"])
def test_print_preparation_requires_server_resolved_active_verified_printer(
    session,
    printer_state,
):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    with session.begin():
        printer = session.scalar(
            select(WarehousePrinter).where(
                WarehousePrinter.warehouse_id == facts["warehouse_id"]
            )
        )
        if printer_state == "missing":
            session.delete(printer)
        elif printer_state == "inactive":
            printer.status = "inactive"
        else:
            printer.status = "verification_failed"

    with session.begin(), pytest.raises(ShippingPrinterUnavailableError):
        ShippingExecutionService(session).prepare_paired_print_jobs(
            **print_command(facts, shipment_id)
        )
    assert session.query(WaybillPrintJob).count() == 0


def test_print_replay_preserves_snapshotted_printer_after_rebind(session):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    first = prepare_print_pair(session, facts, shipment_id)

    with session.begin():
        printer = session.scalar(
            select(WarehousePrinter).where(
                WarehousePrinter.warehouse_id == facts["warehouse_id"]
            )
        )
        printer.printer_sn = "KM-PRINTER-NEW"
        printer.display_name = "新打印机"
        printer.last_verified_at = NOW
    with session.begin():
        replay = ShippingExecutionService(session).prepare_paired_print_jobs(
            **print_command(facts, shipment_id)
        )
        rows = tuple(session.scalars(select(WaybillPrintJob)))
        snapshotted_printers = {row.printer_sn_snapshot for row in rows}

    assert replay.idempotent_replay is True
    assert replay.first_label.print_job_id == first.first_label.print_job_id
    assert snapshotted_printers == {"KM-PRINTER-001"}
    with session.begin(), pytest.raises(ShippingPrinterUnavailableError):
        ShippingExecutionService(session).mark_print_submitting(
            print_job_id=first.first_label.print_job_id,
            label_kind=PrintLabelKind.FIRST,
            expected_status="prepared",
            submitted_at=NOW,
        )
    with session.begin():
        assert session.get(
            WaybillPrintJob,
            first.first_label.print_job_id,
        ).status == "prepared"


def test_print_public_refs_never_expose_internal_accessory_uuid(session):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    accessory_uuid = "d4444444-4444-4444-8444-444444444444"

    with session.begin(), pytest.raises(ShippingInputError) as caught:
        ShippingExecutionService(session).prepare_paired_print_jobs(
            **print_command(
                facts,
                shipment_id,
                return_contact_snapshot={
                    "contact_name": "仓库联系人",
                    "accessory_unit_uuid": accessory_uuid,
                },
            )
        )
    assert accessory_uuid not in str(caught.value)

    pair = prepare_print_pair(session, facts, shipment_id)
    rendered = repr(asdict(pair))
    assert "snapshot" not in rendered
    assert "accessory" not in rendered
    assert accessory_uuid not in rendered


def test_first_label_must_finish_before_second_and_task_ids_are_separate(session):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    pair = prepare_print_pair(session, facts, shipment_id)
    service = ShippingExecutionService(session)

    with session.begin(), pytest.raises(ShippingStateConflictError):
        service.mark_print_submitting(
            print_job_id=pair.second_label.print_job_id,
            label_kind=PrintLabelKind.SECOND,
            expected_status="prepared",
            submitted_at=NOW,
        )

    with session.begin():
        service.mark_print_submitting(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="prepared",
            submitted_at=NOW,
        )
        first = service.record_print_result(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="provider_submitting",
            outcome=PrintOutcome.PRINTED,
            completed_at=NOW,
            provider_task_id="KM-FIRST-TASK",
        )
        assert first.provider_task_id == "KM-FIRST-TASK"

    with session.begin():
        service.mark_print_submitting(
            print_job_id=pair.second_label.print_job_id,
            label_kind="second",
            expected_status="prepared",
            submitted_at=NOW,
        )
        second = service.record_print_result(
            print_job_id=pair.second_label.print_job_id,
            label_kind="second",
            expected_status="provider_submitting",
            outcome="printed",
            completed_at=NOW,
            provider_task_id="KM-SECOND-TASK",
        )
        assert second.provider_task_id == "KM-SECOND-TASK"
        assert second.provider_task_id != first.provider_task_id


def test_unknown_print_requires_reconcile_before_explicit_retry(session):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    pair = prepare_print_pair(session, facts, shipment_id)
    service = ShippingExecutionService(session)

    with session.begin():
        service.mark_print_submitting(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="prepared",
            submitted_at=NOW,
        )
        unknown = service.record_print_result(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="provider_submitting",
            outcome="unknown",
            completed_at=NOW,
        )
        assert unknown.status == "unknown"

    with session.begin(), pytest.raises(ShippingUnknownOutcomeError):
        service.mark_print_submitting(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="prepared",
            submitted_at=NOW,
        )

    with session.begin():
        review = service.reconcile_unknown_print(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            resolution="still_unknown",
            reconciled_at=NOW,
            safe_error_code="PRINT_STILL_UNKNOWN",
        )
        assert review.status == "needs_review"

    with session.begin(), pytest.raises(ShippingUnknownOutcomeError):
        service.mark_print_submitting(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="failed",
            submitted_at=NOW,
        )

    with session.begin():
        failed = service.reconcile_unknown_print(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            resolution="confirmed_no_effect",
            reconciled_at=NOW,
            safe_error_code="PRINT_NOT_SUBMITTED",
        )
        assert failed.status == "failed"
        retry = service.mark_print_submitting(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="failed",
            submitted_at=NOW,
        )
        assert retry.status == "provider_submitting"


def test_device_move_after_print_snapshot_blocks_both_label_submission(session):
    facts = seed_inventory(session)
    shipment_id = submit_shipment(session, facts)
    pair = prepare_print_pair(session, facts, shipment_id)
    service = ShippingExecutionService(session)

    with session.begin():
        other = Warehouse(
            name="新仓",
            status="active",
            setup_state="ready",
            is_default=False,
            contact_name="联系人",
            contact_phone="13800138002",
            province="省",
            city="市",
            district="区",
            address_detail="新仓路",
        )
        session.add(other)
        session.flush()
        session.get(Device, facts["device_id"]).warehouse_id = other.id

    with session.begin(), pytest.raises(ShippingSnapshotMismatchError):
        service.mark_print_submitting(
            print_job_id=pair.first_label.print_job_id,
            label_kind="first",
            expected_status="prepared",
            submitted_at=NOW,
        )


def test_no_provider_adapter_or_network_is_invoked_by_state_service(
    session,
    monkeypatch,
):
    facts = seed_inventory(session)

    def forbidden(*args, **kwargs):
        raise AssertionError("network/provider call was attempted")

    monkeypatch.setattr("socket.create_connection", forbidden)
    shipment_id = submit_shipment(session, facts)
    pair = prepare_print_pair(session, facts, shipment_id)

    assert UUID(shipment_id)
    assert UUID(pair.first_label.print_job_id)
