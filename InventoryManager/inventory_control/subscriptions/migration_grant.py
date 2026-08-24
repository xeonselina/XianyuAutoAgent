"""Deterministic default-tenant migration grant (D60)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

from inventory_control.crypto import CryptoCodecV1


DEFAULT_TENANT_MIGRATION_GRANT_DAYS = 36_500
DEFAULT_TENANT_MIGRATION_GRANT_DURATION = timedelta(
    days=DEFAULT_TENANT_MIGRATION_GRANT_DAYS
)
_BASELINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_GRANT_NAMESPACE = UUID("e02683f2-5dc9-4f9e-a35c-b534c2820c17")


@dataclass(frozen=True, slots=True)
class DefaultTenantMigrationGrant:
    tenant_uuid: UUID
    database_uuid: UUID
    baseline_migration_id: str
    migration_idempotency_key: str
    source_uuid: UUID
    effective_at: datetime
    expires_at: datetime
    source_identity_digest: bytes

    @property
    def duration(self) -> timedelta:
        return self.expires_at - self.effective_at


def calculate_default_tenant_migration_grant(
    *,
    tenant_uuid: UUID,
    database_uuid: UUID,
    baseline_migration_id: str,
    migration_idempotency_key: str,
    database_now: datetime,
) -> DefaultTenantMigrationGrant:
    """Create the fixed 36,500-day grant from authoritative database UTC."""

    if not isinstance(tenant_uuid, UUID) or not isinstance(database_uuid, UUID):
        raise TypeError("migration grant identities must use UUIDs")
    if not isinstance(baseline_migration_id, str) or not _BASELINE_ID.fullmatch(
        baseline_migration_id
    ):
        raise ValueError("baseline migration identity is invalid")
    if not isinstance(migration_idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(
        migration_idempotency_key
    ):
        raise ValueError("migration idempotency key is invalid")
    if (
        not isinstance(database_now, datetime)
        or database_now.tzinfo is None
        or database_now.utcoffset() is None
    ):
        raise ValueError("database_now must be timezone-aware")
    effective_at = database_now.astimezone(timezone.utc)
    try:
        expires_at = effective_at + DEFAULT_TENANT_MIGRATION_GRANT_DURATION
    except OverflowError:
        raise ValueError("migration grant is outside the supported time range") from None

    identity = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain("inventory-manager/default-tenant-migration-grant/v1"),
        CryptoCodecV1.uuid_bytes(tenant_uuid),
        CryptoCodecV1.uuid_bytes(database_uuid),
        CryptoCodecV1.ascii_text(baseline_migration_id),
        CryptoCodecV1.ascii_text(migration_idempotency_key),
    )
    source_identity_digest = hashlib.sha256(identity).digest()
    return DefaultTenantMigrationGrant(
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        baseline_migration_id=baseline_migration_id,
        migration_idempotency_key=migration_idempotency_key,
        source_uuid=uuid5(_GRANT_NAMESPACE, source_identity_digest.hex()),
        effective_at=effective_at,
        expires_at=expires_at,
        source_identity_digest=source_identity_digest,
    )
