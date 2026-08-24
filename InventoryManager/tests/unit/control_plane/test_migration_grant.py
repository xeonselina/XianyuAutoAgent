from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.subscriptions import (
    DEFAULT_TENANT_MIGRATION_GRANT_DAYS,
    DEFAULT_TENANT_MIGRATION_GRANT_DURATION,
    calculate_default_tenant_migration_grant,
)


TENANT_UUID = UUID("10000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("10000000-0000-4000-8000-000000000002")


def test_default_tenant_gets_exactly_36500_days_from_database_utc() -> None:
    database_now = datetime(
        2026,
        8,
        22,
        20,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )

    grant = calculate_default_tenant_migration_grant(
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        baseline_migration_id="initial-baseline-v1",
        migration_idempotency_key="default-tenant:v1",
        database_now=database_now,
    )

    assert DEFAULT_TENANT_MIGRATION_GRANT_DAYS == 36_500
    assert grant.effective_at == datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)
    assert grant.duration == DEFAULT_TENANT_MIGRATION_GRANT_DURATION
    assert grant.duration.total_seconds() == 36_500 * 24 * 60 * 60
    assert len(grant.source_identity_digest) == 32
    assert isinstance(grant.source_uuid, UUID)


def test_grant_identity_is_stable_and_binds_tenant_database_and_baseline() -> None:
    kwargs = {
        "tenant_uuid": TENANT_UUID,
        "database_uuid": DATABASE_UUID,
        "baseline_migration_id": "initial-baseline-v1",
        "migration_idempotency_key": "default-tenant:v1",
        "database_now": datetime(2026, 8, 22, tzinfo=timezone.utc),
    }
    first = calculate_default_tenant_migration_grant(**kwargs)
    retry = calculate_default_tenant_migration_grant(**kwargs)
    assert first.source_identity_digest == retry.source_identity_digest

    variants = [
        {**kwargs, "tenant_uuid": UUID("20000000-0000-4000-8000-000000000001")},
        {**kwargs, "database_uuid": UUID("20000000-0000-4000-8000-000000000002")},
        {**kwargs, "baseline_migration_id": "initial-baseline-v2"},
        {**kwargs, "migration_idempotency_key": "default-tenant:v2"},
    ]
    assert all(
        calculate_default_tenant_migration_grant(**variant).source_identity_digest
        != first.source_identity_digest
        for variant in variants
    )


@pytest.mark.parametrize(
    "database_now",
    [None, datetime(2026, 8, 22)],
)
def test_grant_requires_authoritative_timezone_aware_time(database_now) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_default_tenant_migration_grant(
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            baseline_migration_id="initial-baseline-v1",
            migration_idempotency_key="default-tenant:v1",
            database_now=database_now,
        )


@pytest.mark.parametrize(
    "baseline",
    ["", "contains space", "含中文", "x" * 257],
)
def test_grant_rejects_ambiguous_baseline_identity(baseline) -> None:
    with pytest.raises(ValueError, match="identity"):
        calculate_default_tenant_migration_grant(
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            baseline_migration_id=baseline,
            migration_idempotency_key="default-tenant:v1",
            database_now=datetime(2026, 8, 22, tzinfo=timezone.utc),
        )
