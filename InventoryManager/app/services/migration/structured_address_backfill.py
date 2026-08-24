"""Explicit, manifest-bound structured rental-address backfill.

Legacy ``destination`` values are free text.  This service deliberately does
not parse or infer province/city/district facts from that text.  A restricted
migration input must provide a reviewed structured address for every selected
row and bind it to a digest of the exact legacy value observed in the source
snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Final

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.models.database_identity import TenantDatabaseIdentity
from app.models.rental import Rental
from inventory_control.default_migration import DefaultTenantMigrationManifest


STRUCTURED_ADDRESS_BACKFILL_POLICY_REVISION: Final = 1
_SAFE_KEY: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}", re.ASCII
)
_SOURCE_DOMAIN: Final = b"inventory-manager/legacy-destination/v1\x00"
_TARGET_DOMAIN: Final = b"inventory-manager/structured-address/v1\x00"
_FIELD_LIMITS: Final = {
    "province": 64,
    "city": 64,
    "district": 64,
    "address_detail": 255,
}


class StructuredAddressBackfillError(RuntimeError):
    code = "STRUCTURED_ADDRESS_BACKFILL_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class StructuredAddressBackfillInputError(StructuredAddressBackfillError):
    code = "STRUCTURED_ADDRESS_BACKFILL_INPUT_INVALID"


class StructuredAddressBackfillTransactionError(
    StructuredAddressBackfillError
):
    code = "STRUCTURED_ADDRESS_BACKFILL_TRANSACTION_INVALID"


class StructuredAddressBackfillIdentityMismatchError(
    StructuredAddressBackfillError
):
    code = "STRUCTURED_ADDRESS_BACKFILL_IDENTITY_MISMATCH"


class StructuredAddressBackfillConflictError(StructuredAddressBackfillError):
    code = "STRUCTURED_ADDRESS_BACKFILL_CONFLICT"


class StructuredAddressBackfillPersistenceError(
    StructuredAddressBackfillError
):
    code = "STRUCTURED_ADDRESS_BACKFILL_PERSISTENCE_FAILED"


def legacy_destination_digest(value: str | None) -> bytes:
    """Commit to an exact legacy value without retaining it in plan evidence."""

    if value is not None and not isinstance(value, str):
        raise StructuredAddressBackfillInputError()
    encoded = json.dumps(
        {"destination": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(_SOURCE_DOMAIN + encoded).digest()


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class StructuredRentalAddressEntry:
    rental_id: int
    expected_parent_rental_id: int | None
    expected_legacy_destination_digest: bytes
    province: str = field(repr=False)
    city: str = field(repr=False)
    district: str = field(repr=False)
    address_detail: str = field(repr=False)

    def __post_init__(self) -> None:
        _positive(self.rental_id)
        if self.expected_parent_rental_id is not None:
            _positive(self.expected_parent_rental_id)
            if self.expected_parent_rental_id == self.rental_id:
                raise StructuredAddressBackfillInputError()
        _digest(self.expected_legacy_destination_digest)
        for name, limit in _FIELD_LIMITS.items():
            value = getattr(self, name)
            if not isinstance(value, str):
                raise StructuredAddressBackfillInputError()
            normalized = value.strip()
            if not normalized or len(normalized) > limit:
                raise StructuredAddressBackfillInputError()
            object.__setattr__(self, name, normalized)

    @property
    def target_digest(self) -> bytes:
        encoded = json.dumps(
            {
                "address_detail": self.address_detail,
                "city": self.city,
                "district": self.district,
                "province": self.province,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(_TARGET_DOMAIN + encoded).digest()

    def __repr__(self) -> str:
        return (
            "StructuredRentalAddressEntry("
            f"rental_id={self.rental_id!r}, "
            f"expected_parent_rental_id={self.expected_parent_rental_id!r}, "
            "address='<redacted>')"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredAddressBackfillPlan:
    parent_manifest_digest: bytes
    migration_idempotency_key: str
    entries: tuple[StructuredRentalAddressEntry, ...]
    policy_revision: int = STRUCTURED_ADDRESS_BACKFILL_POLICY_REVISION

    def __post_init__(self) -> None:
        _digest(self.parent_manifest_digest)
        if (
            not isinstance(self.migration_idempotency_key, str)
            or _SAFE_KEY.fullmatch(self.migration_idempotency_key) is None
            or self.policy_revision
            != STRUCTURED_ADDRESS_BACKFILL_POLICY_REVISION
            or not isinstance(self.entries, tuple)
            or not self.entries
            or not all(
                isinstance(item, StructuredRentalAddressEntry)
                for item in self.entries
            )
        ):
            raise StructuredAddressBackfillInputError()
        rental_ids = tuple(item.rental_id for item in self.entries)
        if rental_ids != tuple(sorted(set(rental_ids))):
            raise StructuredAddressBackfillInputError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(self.canonical_bytes()).digest()

    def canonical_bytes(self) -> bytes:
        """Return a PII-free plan identity containing only commitments."""

        return json.dumps(
            {
                "entries": [
                    {
                        "expected_legacy_destination_digest": (
                            item.expected_legacy_destination_digest.hex()
                        ),
                        "expected_parent_rental_id": (
                            item.expected_parent_rental_id
                        ),
                        "rental_id": item.rental_id,
                        "target_digest": item.target_digest.hex(),
                    }
                    for item in self.entries
                ],
                "migration_idempotency_key": self.migration_idempotency_key,
                "parent_manifest_digest": self.parent_manifest_digest.hex(),
                "policy_revision": self.policy_revision,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredAddressBackfillResult:
    plan_digest: bytes
    result_digest: bytes
    addressed_rental_count: int
    updated_row_count: int
    idempotent_replay: bool

    def __post_init__(self) -> None:
        _digest(self.plan_digest)
        _digest(self.result_digest)
        for value in (self.addressed_rental_count, self.updated_row_count):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise StructuredAddressBackfillPersistenceError()
        if (
            self.updated_row_count > self.addressed_rental_count
            or not isinstance(self.idempotent_replay, bool)
            or self.idempotent_replay != (self.updated_row_count == 0)
        ):
            raise StructuredAddressBackfillPersistenceError()


class StructuredAddressBackfillService:
    """Populate reviewed structured facts in one caller-owned transaction."""

    def backfill(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        expected_schema_generation: int,
        plan: StructuredAddressBackfillPlan,
    ) -> StructuredAddressBackfillResult:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or not isinstance(plan, StructuredAddressBackfillPlan)
            or plan.parent_manifest_digest != manifest.digest
            or plan.migration_idempotency_key
            != manifest.migration_idempotency_key
        ):
            raise StructuredAddressBackfillInputError()
        generation = _positive(expected_schema_generation)
        _require_explicit_transaction(session)

        updated = 0
        result_rows: list[dict[str, object]] = []
        try:
            with session.begin_nested():
                identities = tuple(
                    session.scalars(
                        sa.select(TenantDatabaseIdentity)
                        .order_by(TenantDatabaseIdentity.singleton_key)
                        .with_for_update()
                        .execution_options(
                            autoflush=False, populate_existing=True
                        )
                    )
                )
                if len(identities) != 1:
                    raise StructuredAddressBackfillIdentityMismatchError()
                identity = identities[0]
                if (
                    identity.singleton_key != 1
                    or identity.tenant_id != str(manifest.tenant_uuid)
                    or identity.database_uuid != str(manifest.database_uuid)
                    or identity.schema_generation != generation
                ):
                    raise StructuredAddressBackfillIdentityMismatchError()

                expected_ids = tuple(item.rental_id for item in plan.entries)
                rentals = tuple(
                    session.scalars(
                        sa.select(Rental)
                        .where(Rental.id.in_(expected_ids))
                        .order_by(Rental.id)
                        .with_for_update()
                        .execution_options(
                            autoflush=False, populate_existing=True
                        )
                    )
                )
                if tuple(item.id for item in rentals) != expected_ids:
                    raise StructuredAddressBackfillConflictError()

                by_id = {item.id: item for item in rentals}
                for entry in plan.entries:
                    rental = by_id[entry.rental_id]
                    if (
                        rental.parent_rental_id
                        != entry.expected_parent_rental_id
                        or legacy_destination_digest(rental.destination)
                        != entry.expected_legacy_destination_digest
                    ):
                        raise StructuredAddressBackfillConflictError()
                    expected = (
                        entry.province,
                        entry.city,
                        entry.district,
                        entry.address_detail,
                    )
                    existing = (
                        rental.customer_province,
                        rental.customer_city,
                        rental.customer_district,
                        rental.customer_address_detail,
                    )
                    if existing == (None, None, None, None):
                        (
                            rental.customer_province,
                            rental.customer_city,
                            rental.customer_district,
                            rental.customer_address_detail,
                        ) = expected
                        updated += 1
                    elif existing != expected:
                        raise StructuredAddressBackfillConflictError()
                    result_rows.append(
                        {
                            "legacy_destination_digest": (
                                entry.expected_legacy_destination_digest.hex()
                            ),
                            "rental_id": rental.id,
                            "target_digest": entry.target_digest.hex(),
                        }
                    )
                session.flush()
        except StructuredAddressBackfillError:
            raise
        except IntegrityError:
            raise StructuredAddressBackfillConflictError() from None
        except SQLAlchemyError:
            raise StructuredAddressBackfillPersistenceError() from None

        result_digest = hashlib.sha256(
            json.dumps(
                result_rows,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()
        return StructuredAddressBackfillResult(
            plan_digest=plan.digest,
            result_digest=result_digest,
            addressed_rental_count=len(plan.entries),
            updated_row_count=updated,
            idempotent_replay=updated == 0,
        )


def _require_explicit_transaction(session: Session) -> None:
    if not isinstance(session, Session):
        raise StructuredAddressBackfillTransactionError()
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise StructuredAddressBackfillTransactionError()


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StructuredAddressBackfillInputError()
    return value


def _digest(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise StructuredAddressBackfillInputError()
    return value


__all__ = [
    "STRUCTURED_ADDRESS_BACKFILL_POLICY_REVISION",
    "StructuredAddressBackfillConflictError",
    "StructuredAddressBackfillError",
    "StructuredAddressBackfillIdentityMismatchError",
    "StructuredAddressBackfillInputError",
    "StructuredAddressBackfillPersistenceError",
    "StructuredAddressBackfillPlan",
    "StructuredAddressBackfillResult",
    "StructuredAddressBackfillService",
    "StructuredAddressBackfillTransactionError",
    "StructuredRentalAddressEntry",
    "legacy_destination_digest",
]
