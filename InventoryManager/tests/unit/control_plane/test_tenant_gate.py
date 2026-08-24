from datetime import datetime, timedelta

import pytest

from inventory_control.domain.tenant_gate import (
    EffectiveTenantGate,
    TenantGateFacts,
    TenantStatus,
    reduce_tenant_gate,
)


NOW = datetime(2026, 8, 22, 0, 0, 0)


def facts(**overrides):
    values = {
        "tenant_status": TenantStatus.ACTIVE,
        "current_access_version": 4,
        "presented_access_version": 4,
        "recovery_hold_released": True,
        "unresolved_suspension": False,
        "subscription_expires_at": NOW + timedelta(days=3650),
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return TenantGateFacts(**values)


def test_active_requires_a_current_unexpired_subscription():
    decision = reduce_tenant_gate(facts())

    assert decision.gate is EffectiveTenantGate.ACTIVE
    assert decision.error_code is None
    assert decision.allows_business_route


@pytest.mark.parametrize(
    ("status", "expected_gate"),
    [
        (TenantStatus.DELETION_COMMITTING, EffectiveTenantGate.DELETED),
        (TenantStatus.DELETED, EffectiveTenantGate.DELETED),
        (
            TenantStatus.DELETION_COOLING_OFF,
            EffectiveTenantGate.DELETION_COOLING_OFF,
        ),
        (TenantStatus.SUSPENDING, EffectiveTenantGate.SUSPENDED),
        (TenantStatus.SUSPENDED, EffectiveTenantGate.SUSPENDED),
        (TenantStatus.RESUMING, EffectiveTenantGate.SUSPENDED),
        (TenantStatus.PROVISIONING, EffectiveTenantGate.PROVISIONING),
        (TenantStatus.EXPIRED, EffectiveTenantGate.EXPIRED),
    ],
)
def test_statuses_fail_closed(status, expected_gate):
    decision = reduce_tenant_gate(facts(tenant_status=status))

    assert decision.gate is expected_gate
    assert not decision.allows_business_route


def test_priority_is_deletion_then_cooling_then_recovery_then_suspension():
    common = {
        "recovery_hold_released": False,
        "unresolved_suspension": True,
        "subscription_expires_at": NOW - timedelta(seconds=1),
    }

    assert reduce_tenant_gate(
        facts(tenant_status=TenantStatus.DELETED, **common)
    ).gate is EffectiveTenantGate.DELETED
    assert reduce_tenant_gate(
        facts(tenant_status=TenantStatus.DELETION_COOLING_OFF, **common)
    ).gate is EffectiveTenantGate.DELETION_COOLING_OFF
    assert reduce_tenant_gate(
        facts(tenant_status=TenantStatus.ACTIVE, **common)
    ).gate is EffectiveTenantGate.RECOVERY_HOLD
    assert reduce_tenant_gate(
        facts(
            tenant_status=TenantStatus.ACTIVE,
            recovery_hold_released=True,
            unresolved_suspension=True,
            subscription_expires_at=NOW - timedelta(seconds=1),
        )
    ).gate is EffectiveTenantGate.SUSPENDED


def test_expiry_is_evaluated_from_database_time_fact():
    decision = reduce_tenant_gate(
        facts(subscription_expires_at=NOW)
    )

    assert decision.gate is EffectiveTenantGate.EXPIRED
    assert decision.error_code == "TENANT_EXPIRED"


def test_access_version_mismatch_fences_before_state_use():
    decision = reduce_tenant_gate(
        facts(presented_access_version=3)
    )

    assert decision.gate is EffectiveTenantGate.STALE_ACCESS
    assert decision.error_code == "STALE_TENANT_ACCESS_VERSION"


def test_internal_evaluation_can_omit_presented_access_version():
    assert reduce_tenant_gate(
        facts(presented_access_version=None)
    ).gate is EffectiveTenantGate.ACTIVE


def test_missing_subscription_fails_closed_for_active_tenant():
    decision = reduce_tenant_gate(facts(subscription_expires_at=None))

    assert decision.gate is EffectiveTenantGate.INVALID_STATE
    assert decision.error_code == "TENANT_STATE_INVALID"


def test_naive_and_aware_time_mix_is_rejected():
    aware_expiry = (NOW + timedelta(days=1)).astimezone()

    with pytest.raises(ValueError, match="timezone"):
        facts(subscription_expires_at=aware_expiry)
