from __future__ import annotations

from uuid import UUID

import pytest

from inventory_control.crypto import RootKey
from inventory_control.default_migration import (
    DEFAULT_TENANT_IDENTITY_INPUT_VERSION,
    DefaultTenantMigrationManifest,
    DefaultTenantIdentityInputError,
    bind_default_tenant_identity_inputs,
    require_default_tenant_identity_inputs_match,
)


ROOT_KEY = RootKey(version=4, material=bytes(range(32)))
TENANT_UUID = UUID("10000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("10000000-0000-4000-8000-000000000002")


def _bind(**overrides):
    values = {
        "root_key": ROOT_KEY,
        "tenant_uuid": TENANT_UUID,
        "database_uuid": DATABASE_UUID,
        "migration_idempotency_key": "default-tenant-2026-08-22",
        "display_name": "  光影  租界  ",
        "first_admin_phone": "138-0013-8000",
    }
    values.update(overrides)
    return bind_default_tenant_identity_inputs(**values)


def test_inputs_are_normalized_bound_and_safe_to_render() -> None:
    bound = _bind()

    assert bound.input_version == DEFAULT_TENANT_IDENTITY_INPUT_VERSION
    assert bound.display_name == "光影 租界"
    assert bound.first_admin_phone_e164 == "+8613800138000"
    assert len(bound.display_name_commitment) == 32
    assert len(bound.first_admin_phone_commitment) == 32
    rendered = repr(bound) + repr(dict(bound.redacted_summary()))
    assert "光影" not in rendered
    assert "13800138000" not in rendered
    assert bound.display_name_commitment.hex() not in rendered
    assert bound.first_admin_phone_commitment.hex() not in rendered


def test_equivalent_inputs_produce_the_same_manifest_commitments() -> None:
    first = _bind()
    retry = _bind(
        display_name="光影 租界",
        first_admin_phone="+86 138 0013 8000",
    )

    assert first.display_name_commitment == retry.display_name_commitment
    assert first.first_admin_phone_commitment == retry.first_admin_phone_commitment


def test_manifest_retry_requires_the_same_controlled_identity_inputs() -> None:
    bound = _bind()
    manifest = DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-2026-08-22",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID("10000000-0000-4000-8000-000000000003"),
        control_schema_head="202608220021",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=b"s" * 32,
        implementation_identity_digest=b"i" * 32,
        migration_bundle_digest=b"m" * 32,
        display_name_input_commitment=bound.display_name_commitment,
        first_admin_phone_input_commitment=bound.first_admin_phone_commitment,
    )

    require_default_tenant_identity_inputs_match(manifest, _bind())
    with pytest.raises(DefaultTenantIdentityInputError):
        require_default_tenant_identity_inputs_match(
            manifest,
            _bind(first_admin_phone="13900139000"),
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"tenant_uuid": UUID("20000000-0000-4000-8000-000000000001")},
        {"database_uuid": UUID("20000000-0000-4000-8000-000000000002")},
        {"migration_idempotency_key": "default-tenant-2026-08-23"},
        {"root_key": RootKey(version=5, material=bytes(range(32)))},
        {"display_name": "光影租界二号"},
        {"first_admin_phone": "13900139000"},
    ],
)
def test_commitments_bind_every_immutable_identity_and_input(changed) -> None:
    original = _bind()
    updated = _bind(**changed)

    assert (
        original.display_name_commitment,
        original.first_admin_phone_commitment,
    ) != (
        updated.display_name_commitment,
        updated.first_admin_phone_commitment,
    )


@pytest.mark.parametrize(
    "display_name",
    [None, "", "   ", "default tenant", "默认租户", "test", "x" * 121, "a\x00b"],
)
def test_missing_placeholder_and_ambiguous_display_names_are_rejected(display_name) -> None:
    with pytest.raises(DefaultTenantIdentityInputError) as caught:
        _bind(display_name=display_name)

    assert "migration identity input rejected" == str(caught.value)
    if display_name:
        assert str(display_name) not in repr(caught.value)


@pytest.mark.parametrize(
    "phone",
    [None, "", "+85291234567", "008613800138000", "1380013800", "13800138000 ext 1"],
)
def test_noncanonical_or_ambiguous_admin_phones_are_rejected_without_echo(phone) -> None:
    with pytest.raises(DefaultTenantIdentityInputError) as caught:
        _bind(first_admin_phone=phone)

    assert "migration identity input rejected" == str(caught.value)
    if phone:
        assert str(phone) not in repr(caught.value)
