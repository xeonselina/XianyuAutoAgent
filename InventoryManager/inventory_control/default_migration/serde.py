"""Strict JSON document boundary for default-migration plans and journals."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping
from uuid import UUID

from inventory_control.crypto import RootKey

from .bundle import DefaultMigrationBundleEvidence
from .identity_inputs import (
    DefaultTenantIdentityInputs,
    bind_default_tenant_identity_inputs,
)
from .manifest import (
    DefaultTenantMigrationManifest,
    MigrationEvidenceError,
    MigrationJournal,
    MigrationManifestError,
    MigrationPhase,
    MigrationPhaseEvidence,
)
from .source_baseline import (
    DefaultSourceBaselineEvidence,
    DefaultSourceBaselineRejected,
)


_MANIFEST_KEYS = frozenset(
    {
        "manifest_version",
        "migration_idempotency_key",
        "tenant_uuid",
        "database_uuid",
        "source_schema_name",
        "baseline_migration_id",
        "core_plan_revision_uuid",
        "control_schema_head",
        "tenant_schema_head",
        "source_snapshot_digest",
        "implementation_identity_digest",
        "migration_bundle_digest",
        "display_name_input_commitment",
        "first_admin_phone_input_commitment",
    }
)
_MANIFEST_IDENTITY_TEMPLATE_KEYS = _MANIFEST_KEYS - {
    "display_name_input_commitment",
    "first_admin_phone_input_commitment",
}
_MANIFEST_SOURCE_BASELINE_IDENTITY_TEMPLATE_KEYS = (
    _MANIFEST_IDENTITY_TEMPLATE_KEYS
    - {
        "source_snapshot_digest",
        "control_schema_head",
        "tenant_schema_head",
        "migration_bundle_digest",
    }
)
_JOURNAL_KEYS = frozenset(
    {
        "journal_version",
        "manifest_digest",
        "completed",
        "tenant_aware_writes_enabled_at",
    }
)
_EVIDENCE_KEYS = frozenset(
    {
        "evidence_version",
        "phase",
        "manifest_digest",
        "input_state_digest",
        "result_state_digest",
        "completed_at",
        "executor_reference",
    }
)


def manifest_to_document(
    manifest: DefaultTenantMigrationManifest,
) -> dict[str, object]:
    if not isinstance(manifest, DefaultTenantMigrationManifest):
        raise TypeError("manifest is invalid")
    return {
        "manifest_version": manifest.manifest_version,
        "migration_idempotency_key": manifest.migration_idempotency_key,
        "tenant_uuid": str(manifest.tenant_uuid),
        "database_uuid": str(manifest.database_uuid),
        "source_schema_name": manifest.source_schema_name,
        "baseline_migration_id": manifest.baseline_migration_id,
        "core_plan_revision_uuid": str(manifest.core_plan_revision_uuid),
        "control_schema_head": manifest.control_schema_head,
        "tenant_schema_head": manifest.tenant_schema_head,
        "source_snapshot_digest": manifest.source_snapshot_digest.hex(),
        "implementation_identity_digest": (
            manifest.implementation_identity_digest.hex()
        ),
        "migration_bundle_digest": manifest.migration_bundle_digest.hex(),
        "display_name_input_commitment": (
            manifest.display_name_input_commitment.hex()
        ),
        "first_admin_phone_input_commitment": (
            manifest.first_admin_phone_input_commitment.hex()
        ),
    }


def manifest_from_document(
    document: Mapping[str, object],
) -> DefaultTenantMigrationManifest:
    value = _mapping(document, "manifest")
    _exact_keys(value, _MANIFEST_KEYS, "manifest")
    try:
        return DefaultTenantMigrationManifest(
            manifest_version=_integer(value["manifest_version"], "manifest_version"),
            migration_idempotency_key=_text(
                value["migration_idempotency_key"],
                "migration_idempotency_key",
            ),
            tenant_uuid=_uuid(value["tenant_uuid"], "tenant_uuid"),
            database_uuid=_uuid(value["database_uuid"], "database_uuid"),
            source_schema_name=_text(
                value["source_schema_name"], "source_schema_name"
            ),
            baseline_migration_id=_text(
                value["baseline_migration_id"], "baseline_migration_id"
            ),
            core_plan_revision_uuid=_uuid(
                value["core_plan_revision_uuid"],
                "core_plan_revision_uuid",
            ),
            control_schema_head=_text(
                value["control_schema_head"], "control_schema_head"
            ),
            tenant_schema_head=_text(
                value["tenant_schema_head"], "tenant_schema_head"
            ),
            source_snapshot_digest=_hex_digest(
                value["source_snapshot_digest"], "source_snapshot_digest"
            ),
            implementation_identity_digest=_hex_digest(
                value["implementation_identity_digest"],
                "implementation_identity_digest",
            ),
            migration_bundle_digest=_hex_digest(
                value["migration_bundle_digest"], "migration_bundle_digest"
            ),
            display_name_input_commitment=_hex_digest(
                value["display_name_input_commitment"],
                "display_name_input_commitment",
            ),
            first_admin_phone_input_commitment=_hex_digest(
                value["first_admin_phone_input_commitment"],
                "first_admin_phone_input_commitment",
            ),
        )
    except MigrationManifestError:
        raise
    except (KeyError, TypeError, ValueError):
        raise MigrationManifestError("manifest document is invalid") from None


def manifest_from_identity_template_document(
    document: Mapping[str, object],
    *,
    root_key: RootKey,
    display_name: object,
    first_admin_phone: object,
) -> tuple[DefaultTenantMigrationManifest, DefaultTenantIdentityInputs]:
    """Bind controlled plaintext inputs to an immutable manifest template."""

    value = _mapping(document, "manifest identity template")
    _exact_keys(
        value,
        _MANIFEST_IDENTITY_TEMPLATE_KEYS,
        "manifest identity template",
    )
    try:
        manifest_version = _integer(value["manifest_version"], "manifest_version")
        migration_idempotency_key = _text(
            value["migration_idempotency_key"],
            "migration_idempotency_key",
        )
        tenant_uuid = _uuid(value["tenant_uuid"], "tenant_uuid")
        database_uuid = _uuid(value["database_uuid"], "database_uuid")
        inputs = bind_default_tenant_identity_inputs(
            root_key=root_key,
            tenant_uuid=tenant_uuid,
            database_uuid=database_uuid,
            migration_idempotency_key=migration_idempotency_key,
            display_name=display_name,
            first_admin_phone=first_admin_phone,
        )
        manifest = DefaultTenantMigrationManifest(
            manifest_version=manifest_version,
            migration_idempotency_key=migration_idempotency_key,
            tenant_uuid=tenant_uuid,
            database_uuid=database_uuid,
            source_schema_name=_text(
                value["source_schema_name"], "source_schema_name"
            ),
            baseline_migration_id=_text(
                value["baseline_migration_id"], "baseline_migration_id"
            ),
            core_plan_revision_uuid=_uuid(
                value["core_plan_revision_uuid"],
                "core_plan_revision_uuid",
            ),
            control_schema_head=_text(
                value["control_schema_head"], "control_schema_head"
            ),
            tenant_schema_head=_text(
                value["tenant_schema_head"], "tenant_schema_head"
            ),
            source_snapshot_digest=_hex_digest(
                value["source_snapshot_digest"], "source_snapshot_digest"
            ),
            implementation_identity_digest=_hex_digest(
                value["implementation_identity_digest"],
                "implementation_identity_digest",
            ),
            migration_bundle_digest=_hex_digest(
                value["migration_bundle_digest"], "migration_bundle_digest"
            ),
            display_name_input_commitment=inputs.display_name_commitment,
            first_admin_phone_input_commitment=(
                inputs.first_admin_phone_commitment
            ),
        )
        return manifest, inputs
    except MigrationManifestError:
        raise
    except (KeyError, TypeError, ValueError):
        raise MigrationManifestError(
            "manifest identity template is invalid"
        ) from None


def manifest_from_source_baseline_identity_template_document(
    document: Mapping[str, object],
    *,
    source_baseline: DefaultSourceBaselineEvidence,
    migration_bundle: DefaultMigrationBundleEvidence,
    root_key: RootKey,
    display_name: object,
    first_admin_phone: object,
) -> tuple[DefaultTenantMigrationManifest, DefaultTenantIdentityInputs]:
    """Bind a verified source document without manual digest transcription."""

    value = _mapping(document, "source-baseline manifest identity template")
    _exact_keys(
        value,
        _MANIFEST_SOURCE_BASELINE_IDENTITY_TEMPLATE_KEYS,
        "source-baseline manifest identity template",
    )
    if not isinstance(source_baseline, DefaultSourceBaselineEvidence):
        raise DefaultSourceBaselineRejected()
    if not isinstance(migration_bundle, DefaultMigrationBundleEvidence):
        raise MigrationManifestError("migration bundle evidence is invalid")
    try:
        if (
            value["source_schema_name"]
            != source_baseline.source_schema_name
            or value["baseline_migration_id"]
            != source_baseline.baseline_migration_id
        ):
            raise DefaultSourceBaselineRejected()
        completed = dict(value)
        completed["source_snapshot_digest"] = (
            source_baseline.source_snapshot_digest.hex()
        )
        completed["control_schema_head"] = (
            migration_bundle.control_schema_head
        )
        completed["tenant_schema_head"] = migration_bundle.tenant_schema_head
        completed["migration_bundle_digest"] = (
            migration_bundle.bundle_digest.hex()
        )
        manifest, inputs = manifest_from_identity_template_document(
            completed,
            root_key=root_key,
            display_name=display_name,
            first_admin_phone=first_admin_phone,
        )
        source_baseline.require_manifest(manifest)
        return manifest, inputs
    except DefaultSourceBaselineRejected:
        raise
    except (KeyError, TypeError, ValueError):
        raise MigrationManifestError(
            "source-baseline manifest identity template is invalid"
        ) from None


def journal_to_document(journal: MigrationJournal) -> dict[str, object]:
    if not isinstance(journal, MigrationJournal):
        raise TypeError("journal is invalid")
    return {
        "journal_version": 1,
        "manifest_digest": journal.manifest_digest.hex(),
        "completed": [
            {
                "evidence_version": item.evidence_version,
                "phase": item.phase.value,
                "manifest_digest": item.manifest_digest.hex(),
                "input_state_digest": item.input_state_digest.hex(),
                "result_state_digest": item.result_state_digest.hex(),
                "completed_at": _format_utc(item.completed_at),
                "executor_reference": item.executor_reference,
            }
            for item in journal.completed
        ],
        "tenant_aware_writes_enabled_at": (
            None
            if journal.tenant_aware_writes_enabled_at is None
            else _format_utc(journal.tenant_aware_writes_enabled_at)
        ),
    }


def journal_from_document(document: Mapping[str, object]) -> MigrationJournal:
    value = _mapping(document, "journal")
    _exact_keys(value, _JOURNAL_KEYS, "journal")
    if _integer(value["journal_version"], "journal_version") != 1:
        raise MigrationEvidenceError("unsupported journal version")
    completed_value = value["completed"]
    if not isinstance(completed_value, list):
        raise MigrationEvidenceError("journal completed evidence is invalid")
    completed: list[MigrationPhaseEvidence] = []
    try:
        for raw_item in completed_value:
            item = _mapping(raw_item, "phase evidence")
            _exact_keys(item, _EVIDENCE_KEYS, "phase evidence")
            completed.append(
                MigrationPhaseEvidence(
                    evidence_version=_integer(
                        item["evidence_version"], "evidence_version"
                    ),
                    phase=MigrationPhase(_text(item["phase"], "phase")),
                    manifest_digest=_hex_digest(
                        item["manifest_digest"], "manifest_digest"
                    ),
                    input_state_digest=_hex_digest(
                        item["input_state_digest"], "input_state_digest"
                    ),
                    result_state_digest=_hex_digest(
                        item["result_state_digest"], "result_state_digest"
                    ),
                    completed_at=_parse_datetime(
                        item["completed_at"], "completed_at"
                    ),
                    executor_reference=_text(
                        item["executor_reference"], "executor_reference"
                    ),
                )
            )
        marker_value = value["tenant_aware_writes_enabled_at"]
        marker = (
            None
            if marker_value is None
            else _parse_datetime(
                marker_value,
                "tenant_aware_writes_enabled_at",
            )
        )
        return MigrationJournal(
            manifest_digest=_hex_digest(
                value["manifest_digest"], "manifest_digest"
            ),
            completed=tuple(completed),
            tenant_aware_writes_enabled_at=marker,
        )
    except MigrationManifestError:
        raise
    except (KeyError, TypeError, ValueError):
        raise MigrationEvidenceError("journal document is invalid") from None


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise MigrationManifestError(f"{field_name} must be an object")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    field_name: str,
) -> None:
    if frozenset(value) != expected:
        raise MigrationManifestError(f"{field_name} fields are invalid")


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise MigrationManifestError(f"{field_name} must be text")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MigrationManifestError(f"{field_name} must be an integer")
    return value


def _uuid(value: object, field_name: str) -> UUID:
    text = _text(value, field_name)
    try:
        parsed = UUID(text)
    except ValueError:
        raise MigrationManifestError(f"{field_name} is invalid") from None
    if str(parsed) != text:
        raise MigrationManifestError(f"{field_name} must be canonical")
    return parsed


def _hex_digest(value: object, field_name: str) -> bytes:
    text = _text(value, field_name)
    if len(text) != 64:
        raise MigrationManifestError(f"{field_name} is invalid")
    try:
        decoded = bytes.fromhex(text)
    except ValueError:
        raise MigrationManifestError(f"{field_name} is invalid") from None
    if text != decoded.hex():
        raise MigrationManifestError(f"{field_name} must use lowercase hex")
    return decoded


def _parse_datetime(value: object, field_name: str) -> datetime:
    text = _text(value, field_name)
    if not text.endswith("Z"):
        raise MigrationEvidenceError(f"{field_name} must be UTC Z time")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        raise MigrationEvidenceError(f"{field_name} is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise MigrationEvidenceError(f"{field_name} must be UTC")
    if _format_utc(parsed) != text:
        raise MigrationEvidenceError(f"{field_name} is not canonical")
    return parsed


def _format_utc(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
