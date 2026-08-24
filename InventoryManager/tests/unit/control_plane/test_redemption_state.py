from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from inventory_control.redemption import (
    RedemptionCodeState,
    RedemptionCodeStateError,
    RedemptionCodeStatus,
    expire_if_due,
    redeem_for_renewal,
    redeem_reserved_registration,
    reserve_for_registration,
    revoke_after_host_restore,
)


NOW = datetime(2026, 8, 22, 12, 0, 0)
CODE_UUID = UUID("10000000-0000-4000-8000-000000000001")
RUN_UUID = UUID("10000000-0000-4000-8000-000000000002")
USER_UUID = UUID("10000000-0000-4000-8000-000000000003")
ATTEMPT_UUID = UUID("10000000-0000-4000-8000-000000000004")
TENANT_UUID = UUID("10000000-0000-4000-8000-000000000005")
COMMIT_UUID = UUID("10000000-0000-4000-8000-000000000006")


def _active(**changes):
    values = {
        "code_uuid": CODE_UUID,
        "status": RedemptionCodeStatus.ACTIVE,
        "redeem_before": NOW + timedelta(days=1),
        "created_under_recovery_run_uuid": RUN_UUID,
    }
    values.update(changes)
    return RedemptionCodeState(**values)


def test_active_code_expires_at_database_deadline_but_reserved_does_not() -> None:
    due = _active(redeem_before=NOW)
    assert expire_if_due(due, database_now=NOW).status is RedemptionCodeStatus.EXPIRED

    reserved = reserve_for_registration(
        _active(redeem_before=NOW + timedelta(seconds=1)),
        user_uuid=USER_UUID,
        registration_attempt_uuid=ATTEMPT_UUID,
        current_recovery_run_uuid=RUN_UUID,
        recovery_run_completed=True,
        database_now=NOW,
    )
    assert expire_if_due(
        reserved,
        database_now=NOW + timedelta(days=365),
    ).status is RedemptionCodeStatus.RESERVED


def test_registration_reservation_is_immutable_and_only_owner_can_finalize() -> None:
    reserved = reserve_for_registration(
        _active(),
        user_uuid=USER_UUID,
        registration_attempt_uuid=ATTEMPT_UUID,
        current_recovery_run_uuid=RUN_UUID,
        recovery_run_completed=True,
        database_now=NOW,
    )

    with pytest.raises(RedemptionCodeStateError) as caught:
        redeem_reserved_registration(
            reserved,
            user_uuid=UUID("20000000-0000-4000-8000-000000000003"),
            registration_attempt_uuid=ATTEMPT_UUID,
            tenant_uuid=TENANT_UUID,
            registration_commit_uuid=COMMIT_UUID,
            current_recovery_run_uuid=RUN_UUID,
            recovery_run_completed=True,
        )
    assert caught.value.code == "CODE_RESERVATION_MISMATCH"

    redeemed = redeem_reserved_registration(
        reserved,
        user_uuid=USER_UUID,
        registration_attempt_uuid=ATTEMPT_UUID,
        tenant_uuid=TENANT_UUID,
        registration_commit_uuid=COMMIT_UUID,
        current_recovery_run_uuid=RUN_UUID,
        recovery_run_completed=True,
    )
    assert redeemed.status is RedemptionCodeStatus.REDEEMED
    assert redeemed.redeemed_tenant_uuid == TENANT_UUID
    assert redeemed.registration_commit_uuid == COMMIT_UUID


def test_renewal_consumes_only_current_run_active_code() -> None:
    redeemed = redeem_for_renewal(
        _active(),
        tenant_uuid=TENANT_UUID,
        current_recovery_run_uuid=RUN_UUID,
        recovery_run_completed=True,
        database_now=NOW,
    )

    assert redeemed.status is RedemptionCodeStatus.REDEEMED
    assert redeemed.redeemed_tenant_uuid == TENANT_UUID
    assert redeemed.reserved_user_uuid is None

    with pytest.raises(RedemptionCodeStateError) as caught:
        redeem_for_renewal(
            _active(),
            tenant_uuid=TENANT_UUID,
            current_recovery_run_uuid=UUID(
                "20000000-0000-4000-8000-000000000002"
            ),
            recovery_run_completed=True,
            database_now=NOW,
        )
    assert caught.value.code == "CODE_NOT_REDEEMABLE"


def test_recovery_must_be_completed_before_reservation_or_redemption() -> None:
    with pytest.raises(RedemptionCodeStateError) as caught:
        reserve_for_registration(
            _active(),
            user_uuid=USER_UUID,
            registration_attempt_uuid=ATTEMPT_UUID,
            current_recovery_run_uuid=RUN_UUID,
            recovery_run_completed=False,
            database_now=NOW,
        )
    assert caught.value.code == "RECOVERY_NOT_COMPLETED"


@pytest.mark.parametrize(
    "status",
    [RedemptionCodeStatus.ACTIVE, RedemptionCodeStatus.RESERVED],
)
def test_host_restore_irreversibly_revokes_live_snapshot_codes(status) -> None:
    if status is RedemptionCodeStatus.RESERVED:
        state = _active(
            status=status,
            reserved_user_uuid=USER_UUID,
            reserved_registration_attempt_uuid=ATTEMPT_UUID,
        )
    else:
        state = _active(status=status)

    revoked = revoke_after_host_restore(state)

    assert revoked.status is RedemptionCodeStatus.RECOVERY_REVOKED
    assert revoke_after_host_restore(revoked) == revoked


@pytest.mark.parametrize(
    "status",
    [
        RedemptionCodeStatus.REDEEMED,
        RedemptionCodeStatus.REVOKED,
        RedemptionCodeStatus.EXPIRED,
        RedemptionCodeStatus.RECOVERY_REVOKED,
    ],
)
def test_host_restore_does_not_weaken_terminal_states(status) -> None:
    values = {}
    if status is RedemptionCodeStatus.REDEEMED:
        values["redeemed_tenant_uuid"] = TENANT_UUID
    state = _active(status=status, **values)

    assert revoke_after_host_restore(state) == state
