"""Versioned recovery policy for jobs that may cross side-effect boundaries.

The durable worker owns the generic submission fence.  This module answers a
different question: after a process loses the exact outcome, which recovery
operation is permitted for each SaaS Core capability?  Keeping the registry
small and immutable prevents individual handlers from inventing a more
permissive retry rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


RECOVERY_POLICY_VERSION = 1


class RecoveryCategory(str, Enum):
    PROVISIONING = "provisioning"
    SMS = "sms"
    SF = "sf"
    PRINT = "print"
    XIANYU_KUAIMAI_SYNC = "xianyu_kuaimai_sync"
    BACKUP = "backup"
    CLEANUP = "cleanup"


class RecoveryStrategy(str, Enum):
    SAFE_RETRY = "safe_retry"
    QUERY_RECONCILE = "query_reconcile"
    EXPLICIT_CONFIRMATION = "explicit_confirmation"


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """Fail-closed policy for an ambiguous post-boundary outcome.

    ``SAFE_RETRY`` still requires the same immutable operation identity and
    fencing generation. ``QUERY_RECONCILE`` permits only current-read/provider
    lookup using the persisted execution snapshot. ``EXPLICIT_CONFIRMATION``
    prohibits automated resubmission until a user or operator establishes the
    physical outcome and creates a newly authorized operation when necessary.
    """

    category: RecoveryCategory
    ambiguous_strategy: RecoveryStrategy
    immutable_snapshot_required: bool
    stable_idempotency_required: bool
    automatic_resubmission_allowed: bool

    def __post_init__(self) -> None:
        category = RecoveryCategory(self.category)
        strategy = RecoveryStrategy(self.ambiguous_strategy)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "ambiguous_strategy", strategy)
        if self.automatic_resubmission_allowed:
            if strategy is not RecoveryStrategy.SAFE_RETRY:
                raise ValueError(
                    "automatic resubmission requires the safe-retry strategy"
                )
            if not self.stable_idempotency_required:
                raise ValueError(
                    "automatic resubmission requires stable idempotency"
                )
        if strategy is RecoveryStrategy.QUERY_RECONCILE:
            if not self.immutable_snapshot_required:
                raise ValueError(
                    "query reconciliation requires an immutable snapshot"
                )
            if self.automatic_resubmission_allowed:
                raise ValueError(
                    "query reconciliation cannot resubmit automatically"
                )
        if strategy is RecoveryStrategy.EXPLICIT_CONFIRMATION:
            if self.automatic_resubmission_allowed:
                raise ValueError(
                    "explicit confirmation cannot resubmit automatically"
                )


def _policy(
    category: RecoveryCategory,
    strategy: RecoveryStrategy,
    *,
    snapshot: bool,
    idempotency: bool,
    resubmit: bool,
) -> RecoveryPolicy:
    return RecoveryPolicy(
        category=category,
        ambiguous_strategy=strategy,
        immutable_snapshot_required=snapshot,
        stable_idempotency_required=idempotency,
        automatic_resubmission_allowed=resubmit,
    )


_POLICIES: Mapping[RecoveryCategory, RecoveryPolicy] = MappingProxyType(
    {
        # Cross-database DDL/account work must first observe the exact
        # provisional tenant/database/generation before any fenced resume.
        RecoveryCategory.PROVISIONING: _policy(
            RecoveryCategory.PROVISIONING,
            RecoveryStrategy.QUERY_RECONCILE,
            snapshot=True,
            idempotency=True,
            resubmit=False,
        ),
        # An unknown SMS delivery keeps the committed challenge usable.  It is
        # never answered by automatically sending another code.
        RecoveryCategory.SMS: _policy(
            RecoveryCategory.SMS,
            RecoveryStrategy.EXPLICIT_CONFIRMATION,
            snapshot=True,
            idempotency=False,
            resubmit=False,
        ),
        # SF creation/cancellation is reconciled by stable provider order
        # identity and the exact historical credential/warehouse snapshot.
        RecoveryCategory.SF: _policy(
            RecoveryCategory.SF,
            RecoveryStrategy.QUERY_RECONCILE,
            snapshot=True,
            idempotency=True,
            resubmit=False,
        ),
        # Physical paper may already exist even when the response was lost.
        RecoveryCategory.PRINT: _policy(
            RecoveryCategory.PRINT,
            RecoveryStrategy.EXPLICIT_CONFIRMATION,
            snapshot=True,
            idempotency=False,
            resubmit=False,
        ),
        # Alert/order synchronization is a read/current-snapshot operation;
        # the same tenant/connection/time-bucket identity may safely rerun.
        RecoveryCategory.XIANYU_KUAIMAI_SYNC: _policy(
            RecoveryCategory.XIANYU_KUAIMAI_SYNC,
            RecoveryStrategy.SAFE_RETRY,
            snapshot=True,
            idempotency=True,
            resubmit=True,
        ),
        # Backup attempts publish only verified completed artifacts. Partial
        # files are isolated and the same artifact identity may retry.
        RecoveryCategory.BACKUP: _policy(
            RecoveryCategory.BACKUP,
            RecoveryStrategy.SAFE_RETRY,
            snapshot=True,
            idempotency=True,
            resubmit=True,
        ),
        # System cleanup is monotonic and can retry only under the original
        # source generation/current-run fence; it never revives old authority.
        RecoveryCategory.CLEANUP: _policy(
            RecoveryCategory.CLEANUP,
            RecoveryStrategy.SAFE_RETRY,
            snapshot=True,
            idempotency=True,
            resubmit=True,
        ),
    }
)


def recovery_policy(category: RecoveryCategory) -> RecoveryPolicy:
    """Return one immutable policy; unknown categories fail closed."""

    if not isinstance(category, RecoveryCategory):
        raise TypeError("category must be a RecoveryCategory")
    return _POLICIES[category]


def recovery_policy_registry() -> Mapping[RecoveryCategory, RecoveryPolicy]:
    """Expose the read-only complete v1 registry for composition checks."""

    return _POLICIES


__all__ = [
    "RECOVERY_POLICY_VERSION",
    "RecoveryCategory",
    "RecoveryPolicy",
    "RecoveryStrategy",
    "recovery_policy",
    "recovery_policy_registry",
]
