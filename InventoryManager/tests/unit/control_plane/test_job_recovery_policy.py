import pytest

from inventory_control.jobs import (
    RECOVERY_POLICY_VERSION,
    RecoveryCategory,
    RecoveryPolicy,
    RecoveryStrategy,
    recovery_policy,
    recovery_policy_registry,
)


def test_registry_is_complete_immutable_and_versioned():
    registry = recovery_policy_registry()

    assert RECOVERY_POLICY_VERSION == 1
    assert set(registry) == set(RecoveryCategory)
    assert all(registry[key].category is key for key in registry)
    with pytest.raises(TypeError):
        registry[RecoveryCategory.SF] = registry[RecoveryCategory.PRINT]


@pytest.mark.parametrize(
    ("category", "strategy"),
    (
        (RecoveryCategory.PROVISIONING, RecoveryStrategy.QUERY_RECONCILE),
        (RecoveryCategory.SMS, RecoveryStrategy.EXPLICIT_CONFIRMATION),
        (RecoveryCategory.SF, RecoveryStrategy.QUERY_RECONCILE),
        (RecoveryCategory.PRINT, RecoveryStrategy.EXPLICIT_CONFIRMATION),
        (RecoveryCategory.XIANYU_KUAIMAI_SYNC, RecoveryStrategy.SAFE_RETRY),
        (RecoveryCategory.BACKUP, RecoveryStrategy.SAFE_RETRY),
        (RecoveryCategory.CLEANUP, RecoveryStrategy.SAFE_RETRY),
    ),
)
def test_ambiguous_outcomes_use_capability_specific_strategy(category, strategy):
    policy = recovery_policy(category)

    assert policy.ambiguous_strategy is strategy
    assert policy.immutable_snapshot_required is True
    assert policy.automatic_resubmission_allowed is (
        strategy is RecoveryStrategy.SAFE_RETRY
    )


def test_unknown_category_does_not_fall_back_to_safe_retry():
    with pytest.raises(TypeError, match="RecoveryCategory"):
        recovery_policy("sf")


def test_policy_cannot_authorize_automatic_replay_without_idempotency():
    with pytest.raises(ValueError, match="stable idempotency"):
        RecoveryPolicy(
            category=RecoveryCategory.BACKUP,
            ambiguous_strategy=RecoveryStrategy.SAFE_RETRY,
            immutable_snapshot_required=True,
            stable_idempotency_required=False,
            automatic_resubmission_allowed=True,
        )


def test_query_reconciliation_cannot_exist_without_snapshot():
    with pytest.raises(ValueError, match="immutable snapshot"):
        RecoveryPolicy(
            category=RecoveryCategory.SF,
            ambiguous_strategy=RecoveryStrategy.QUERY_RECONCILE,
            immutable_snapshot_required=False,
            stable_idempotency_required=True,
            automatic_resubmission_allowed=False,
        )
