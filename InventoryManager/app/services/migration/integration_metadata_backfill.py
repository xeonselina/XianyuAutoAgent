"""Metadata-only integration ownership backfill for the default tenant.

This adapter intentionally has no credential argument.  It can establish
stable SF/Kuaimai/Xianyu connection identities and bounded non-secret config,
but cannot read, hash, encrypt, wrap, validate or submit any legacy value.  New
provider-rotated credentials use the separate revision/verification workflow.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from inventory_control.default_migration import DefaultTenantMigrationManifest
from inventory_control.integrations import (
    IntegrationInputError,
    TenantIntegrationRef,
    TenantIntegrationService,
)


class IntegrationMetadataBackfillError(RuntimeError):
    code = "INTEGRATION_METADATA_BACKFILL_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class IntegrationMetadataBackfillInputError(IntegrationMetadataBackfillError):
    code = "INTEGRATION_METADATA_BACKFILL_INPUT_INVALID"


class IntegrationMetadataBackfillConflictError(IntegrationMetadataBackfillError):
    code = "INTEGRATION_METADATA_BACKFILL_CONFLICT"


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegrationMetadataBackfillEntry:
    provider: str
    name: str
    config: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.provider not in {"sf", "kuaimai", "xianyu"}:
            raise IntegrationMetadataBackfillInputError()
        if not isinstance(self.name, str) or not self.name.strip():
            raise IntegrationMetadataBackfillInputError()
        if not isinstance(self.config, Mapping) or dict(self.config):
            raise IntegrationMetadataBackfillInputError()
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "config", {})


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegrationMetadataBackfillPlan:
    parent_manifest_digest: bytes
    migration_idempotency_key: str
    entries: tuple[IntegrationMetadataBackfillEntry, ...]
    policy_revision: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parent_manifest_digest, bytes)
            or len(self.parent_manifest_digest) != 32
            or not isinstance(self.migration_idempotency_key, str)
            or not self.migration_idempotency_key
            or self.policy_revision != 1
            or not isinstance(self.entries, tuple)
            or not self.entries
            or not all(
                isinstance(item, IntegrationMetadataBackfillEntry)
                for item in self.entries
            )
        ):
            raise IntegrationMetadataBackfillInputError()
        identities = tuple((item.provider, item.name) for item in self.entries)
        if identities != tuple(sorted(set(identities))):
            raise IntegrationMetadataBackfillInputError()
        try:
            self.canonical_bytes()
        except (TypeError, ValueError):
            raise IntegrationMetadataBackfillInputError() from None

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(self.canonical_bytes()).digest()

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "entries": [
                    {
                        "config": dict(item.config),
                        "name": item.name,
                        "provider": item.provider,
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
            allow_nan=False,
        ).encode("ascii")


@dataclass(frozen=True, slots=True, kw_only=True)
class IntegrationMetadataBackfillResult:
    plan_digest: bytes
    integrations: tuple[TenantIntegrationRef, ...]
    created_count: int
    replayed_count: int


class IntegrationMetadataBackfillService:
    """Create/replay metadata through the non-secret integration API only."""

    def backfill(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        plan: IntegrationMetadataBackfillPlan,
    ) -> IntegrationMetadataBackfillResult:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or not isinstance(plan, IntegrationMetadataBackfillPlan)
            or plan.parent_manifest_digest != manifest.digest
            or plan.migration_idempotency_key
            != manifest.migration_idempotency_key
        ):
            raise IntegrationMetadataBackfillInputError()
        service = TenantIntegrationService(session)
        refs: list[TenantIntegrationRef] = []
        try:
            with session.begin_nested():
                for entry in plan.entries:
                    integration_uuid = _integration_uuid(
                        tenant_uuid=manifest.tenant_uuid,
                        migration_idempotency_key=(
                            manifest.migration_idempotency_key
                        ),
                        provider=entry.provider,
                        name=entry.name,
                    )
                    refs.append(
                        service.create_integration(
                            integration_uuid=integration_uuid,
                            tenant_uuid=manifest.tenant_uuid,
                            provider=entry.provider,
                            name=entry.name,
                            config=entry.config,
                        )
                    )
        except IntegrationInputError:
            raise IntegrationMetadataBackfillInputError() from None
        except Exception:
            raise IntegrationMetadataBackfillConflictError() from None
        return IntegrationMetadataBackfillResult(
            plan_digest=plan.digest,
            integrations=tuple(refs),
            created_count=sum(not item.idempotent_replay for item in refs),
            replayed_count=sum(item.idempotent_replay for item in refs),
        )


def _integration_uuid(
    *,
    tenant_uuid: UUID,
    migration_idempotency_key: str,
    provider: str,
    name: str,
) -> UUID:
    return uuid5(
        tenant_uuid,
        "inventory-manager/default-integration-metadata/v1/"
        f"{migration_idempotency_key}/{provider}/{name}",
    )


__all__ = [
    "IntegrationMetadataBackfillConflictError",
    "IntegrationMetadataBackfillEntry",
    "IntegrationMetadataBackfillError",
    "IntegrationMetadataBackfillInputError",
    "IntegrationMetadataBackfillPlan",
    "IntegrationMetadataBackfillResult",
    "IntegrationMetadataBackfillService",
]
