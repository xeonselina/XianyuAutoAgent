from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from uuid import UUID

import pytest

from app import db
from app.models.device import Device
from app.models.rental import Rental
from app.models.shipping_execution import OutboundShipment
from app.models.warehouse import Warehouse
from app.services.shipping import (
    ShipmentTrackingQueryService,
    TrackingCredentialContextError,
    TrackingQueryInputError,
    TrackingShipmentUnavailableError,
)
from inventory_control.integrations import SfProviderExecutionContext


TENANT_UUID = "10000000-0000-4000-8000-000000000001"
WAREHOUSE_UUID = "20000000-0000-4000-8000-000000000001"
INTEGRATION_UUID = "30000000-0000-4000-8000-000000000001"
ACCOUNT_UUID = "40000000-0000-4000-8000-000000000001"
INTEGRATION_REVISION_UUID = "50000000-0000-4000-8000-000000000001"
ACCOUNT_REVISION_UUID = "60000000-0000-4000-8000-000000000001"
SECOND_ACCOUNT_REVISION_UUID = "60000000-0000-4000-8000-000000000002"
CLAIM_UUID = "70000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 8, 23, 5, 0, 0)


@pytest.fixture
def session(application):
    return db.session()


def _seed_inventory(session):
    with session.begin():
        warehouse = Warehouse(
            warehouse_uuid=WAREHOUSE_UUID,
            name="轨迹测试仓",
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
        device = Device(name="轨迹测试设备", warehouse=warehouse)
        rental = Rental(
            device=device,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            customer_name="不应进入摘要的客户",
            customer_phone="13900139000",
            destination="不应进入摘要的地址",
        )
        session.add_all((warehouse, device, rental))
        session.flush()
        return warehouse.id, rental.id


def _shipment(
    *,
    shipment_id,
    rental_id,
    warehouse_id,
    waybill_no,
    submitted_at,
    status="submitted",
    phone_last4="9000",
    account_revision_uuid=ACCOUNT_REVISION_UUID,
):
    suffix = str(shipment_id).replace("-", "")[-12:]
    return OutboundShipment(
        id=str(shipment_id),
        provider="sf",
        rental_id=rental_id,
        origin_warehouse_id=warehouse_id,
        origin_warehouse_uuid=WAREHOUSE_UUID,
        integration_uuid=INTEGRATION_UUID,
        provider_account_uuid=ACCOUNT_UUID,
        integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
        provider_account_secret_revision_uuid=account_revision_uuid,
        binding_revision=7,
        account_masked_hint="****0001",
        sender_snapshot={"contact_name": "server-derived"},
        receiver_snapshot={"contact_phone": "13900139000"},
        cargo_snapshot={"items": [{"name": "租赁设备", "count": 1}]},
        tracking_check_phone_last4=phone_last4,
        express_type_id=2,
        scheduled_dispatch_at=(submitted_at - timedelta(minutes=2)),
        provider_order_id=f"shipment-tracking:{suffix}",
        request_hash="a" * 64,
        waybill_no=waybill_no,
        status=status,
        submitted_at=submitted_at,
        prepared_at=submitted_at - timedelta(minutes=1),
        created_at=submitted_at - timedelta(minutes=1),
        updated_at=submitted_at,
    )


def _seed_three_trackable_shipments(session):
    warehouse_id, rental_id = _seed_inventory(session)
    ids = (
        "80000000-0000-4000-8000-000000000001",
        "80000000-0000-4000-8000-000000000002",
        "80000000-0000-4000-8000-000000000003",
    )
    with session.begin():
        session.add_all(
            (
                _shipment(
                    shipment_id=ids[0],
                    rental_id=rental_id,
                    warehouse_id=warehouse_id,
                    waybill_no="SF-TRACK-1",
                    submitted_at=NOW,
                ),
                _shipment(
                    shipment_id=ids[1],
                    rental_id=rental_id,
                    warehouse_id=warehouse_id,
                    waybill_no="SF-TRACK-2",
                    submitted_at=NOW,
                    status="cancelled",
                ),
                _shipment(
                    shipment_id=ids[2],
                    rental_id=rental_id,
                    warehouse_id=warehouse_id,
                    waybill_no="SF-TRACK-3",
                    submitted_at=NOW + timedelta(hours=1),
                    phone_last4="8000",
                    account_revision_uuid=SECOND_ACCOUNT_REVISION_UUID,
                ),
            )
        )
    return ids


def test_list_uses_stable_keyset_cursor_and_excludes_pii(session):
    ids = _seed_three_trackable_shipments(session)
    service = ShipmentTrackingQueryService(session)

    first = service.list_shipments(page_size=2)
    assert [item.shipment_id for item in first.items] == [ids[2], ids[1]]
    assert first.next_cursor is not None
    assert "customer_name" not in asdict(first.items[0])
    assert "receiver_snapshot" not in asdict(first.items[0])
    assert "integration_secret_revision_uuid" not in asdict(first.items[0])

    second = service.list_shipments(
        page_size=2,
        after_cursor=first.next_cursor,
    )
    assert [item.shipment_id for item in second.items] == [ids[0]]
    assert second.next_cursor is None


@pytest.mark.parametrize(
    "page_size,cursor",
    ((0, None), (101, None), (True, None), (20, "not-a-cursor")),
)
def test_list_rejects_unbounded_or_malformed_pagination(
    session,
    page_size,
    cursor,
):
    with pytest.raises(TrackingQueryInputError):
        ShipmentTrackingQueryService(session).list_shipments(
            page_size=page_size,
            after_cursor=cursor,
        )


def test_batch_plan_groups_by_exact_revision_and_phone_without_current_lookup(
    session,
):
    ids = _seed_three_trackable_shipments(session)
    service = ShipmentTrackingQueryService(session)

    batches = service.plan_historical_batches(
        shipment_ids=(ids[1], ids[0], ids[2], ids[1]),
    )

    assert len(batches) == 2
    assert [item.shipment_id for item in batches[0].shipments] == [
        ids[1],
        ids[0],
    ]
    assert batches[0].phone_last4 == "9000"
    assert batches[0].provider_account_secret_revision_uuid == (ACCOUNT_REVISION_UUID)
    assert batches[1].phone_last4 == "8000"
    assert batches[1].provider_account_secret_revision_uuid == (
        SECOND_ACCOUNT_REVISION_UUID
    )

    calls = []

    def load_historical(**kwargs):
        calls.append(kwargs)
        account_revision = kwargs["provider_account_secret_revision_uuid"]
        return SfProviderExecutionContext(
            tenant_uuid=kwargs["tenant_uuid"],
            warehouse_uuid=kwargs["warehouse_uuid"],
            provider_account_uuid=ACCOUNT_UUID,
            integration_uuid=INTEGRATION_UUID,
            integration_secret_revision_uuid=(
                kwargs["integration_secret_revision_uuid"]
            ),
            provider_account_secret_revision_uuid=account_revision,
            global_claim_uuid=CLAIM_UUID,
            claim_generation=3,
            binding_revision=kwargs["binding_revision"],
            masked_account_hint="****0001",
            historical=True,
        )

    resolved = service.resolve_historical_batches(
        tenant_uuid=TENANT_UUID,
        batches=batches,
        context_loader=load_historical,
    )

    assert len(resolved) == 2
    assert [call["provider_account_secret_revision_uuid"] for call in calls] == [
        ACCOUNT_REVISION_UUID,
        SECOND_ACCOUNT_REVISION_UUID,
    ]
    assert all("provider_account_uuid" not in call for call in calls)
    assert all(batch.provider_context.historical for batch in resolved)


def test_batch_resolution_rejects_context_that_follows_a_different_revision(
    session,
):
    ids = _seed_three_trackable_shipments(session)
    batch = ShipmentTrackingQueryService(session).plan_historical_batches(
        shipment_ids=(ids[0],)
    )[0]
    mismatched = SfProviderExecutionContext(
        tenant_uuid=TENANT_UUID,
        warehouse_uuid=WAREHOUSE_UUID,
        provider_account_uuid=ACCOUNT_UUID,
        integration_uuid=INTEGRATION_UUID,
        integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
        provider_account_secret_revision_uuid=SECOND_ACCOUNT_REVISION_UUID,
        global_claim_uuid=CLAIM_UUID,
        claim_generation=3,
        binding_revision=7,
        masked_account_hint="****0001",
        historical=True,
    )

    with pytest.raises(TrackingCredentialContextError):
        ShipmentTrackingQueryService.resolve_historical_batches(
            tenant_uuid=TENANT_UUID,
            batches=(batch,),
            context_loader=lambda **_kwargs: mismatched,
        )


def test_batch_plan_fails_closed_for_missing_or_invalid_historical_snapshot(
    session,
):
    ids = _seed_three_trackable_shipments(session)
    service = ShipmentTrackingQueryService(session)
    with pytest.raises(TrackingShipmentUnavailableError):
        service.plan_historical_batches(
            shipment_ids=("90000000-0000-4000-8000-000000000001",)
        )

    session.rollback()
    with session.begin():
        session.get(OutboundShipment, ids[0]).tracking_check_phone_last4 = "90x0"
    with pytest.raises(TrackingShipmentUnavailableError):
        service.plan_historical_batches(shipment_ids=(ids[0],))


def test_batch_plan_chunks_same_historical_context_at_provider_limit(session):
    warehouse_id, rental_id = _seed_inventory(session)
    shipment_ids = tuple(str(UUID(int=index + 1)) for index in range(101))
    with session.begin():
        session.add_all(
            _shipment(
                shipment_id=shipment_id,
                rental_id=rental_id,
                warehouse_id=warehouse_id,
                waybill_no=f"SF-BULK-{index:03d}",
                submitted_at=NOW,
                status="cancelled",
            )
            for index, shipment_id in enumerate(shipment_ids)
        )

    batches = ShipmentTrackingQueryService(session).plan_historical_batches(
        shipment_ids=shipment_ids
    )

    assert [len(batch.shipments) for batch in batches] == [100, 1]
