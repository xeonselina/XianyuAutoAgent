from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.crypto import RootKey
from inventory_control.domain.rbac import TenantRole
from inventory_control.domain.tenant_gate import EffectiveTenantGate
from inventory_control.proofs import (
    CurrentGanttPreviewAuthority,
    GanttPreviewAuthority,
    GanttPreviewAuthorityError,
    GanttPreviewContent,
    GanttPreviewFenceReleaseUncertain,
    GanttPreviewProofError,
    GanttPreviewProofAdapter,
)
from inventory_control.tenant_http import AuthContext


ROOT_KEY = RootKey(version=9, material=b"g" * 32)
NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)


def _auth_context(**changes) -> AuthContext:
    values = {
        "session_id": "10000000-0000-4000-8000-000000000003",
        "user_id": "10000000-0000-4000-8000-000000000002",
        "membership_id": "10000000-0000-4000-8000-000000000006",
        "tenant_id": "10000000-0000-4000-8000-000000000001",
        "role": TenantRole.OPERATOR,
        "user_auth_version": 4,
        "tenant_access_version": 8,
        "tenant_timezone": "Asia/Shanghai",
        "effective_gate": EffectiveTenantGate.ACTIVE,
    }
    values.update(changes)
    return AuthContext(**values)


def _authority(**changes) -> GanttPreviewAuthority:
    values = {
        "tenant_uuid": UUID("10000000-0000-4000-8000-000000000001"),
        "actor_user_uuid": UUID("10000000-0000-4000-8000-000000000002"),
        "actor_session_uuid": UUID("10000000-0000-4000-8000-000000000003"),
        "user_auth_version": 4,
        "tenant_access_version": 8,
        "tenant_timezone": "Asia/Shanghai",
        "recovery_run_uuid": UUID("10000000-0000-4000-8000-000000000004"),
        "recovery_hold_uuid": UUID("10000000-0000-4000-8000-000000000005"),
        "recovery_hold_revision": 2,
    }
    values.update(changes)
    return GanttPreviewAuthority(**values)


def _content() -> GanttPreviewContent:
    return GanttPreviewContent.from_values(
        snapshot_hash="ab" * 32,
        decisions=[],
        assignments={10: 3},
        preview_date=date(2026, 8, 22),
        solver_version="cp-sat-v1",
    )


class MutableAuthorityReader:
    def __init__(self) -> None:
        self.current = CurrentGanttPreviewAuthority(
            authority=_authority(),
            membership_uuid=UUID(
                "10000000-0000-4000-8000-000000000006"
            ),
            role=TenantRole.OPERATOR,
            session_is_current=True,
            effective_gate=EffectiveTenantGate.ACTIVE,
        active_root_key=ROOT_KEY,
        database_now=NOW,
        tenant_timezone="Asia/Shanghai",
        )
        self.calls: list[AuthContext] = []
        self.fence_events: list[str] = []
        self.error: Exception | None = None

    def read_current(
        self,
        *,
        auth_context: AuthContext,
    ) -> CurrentGanttPreviewAuthority:
        self.calls.append(auth_context)
        if self.error is not None:
            raise self.error
        return self.current

    @contextmanager
    def lock_current(self, *, auth_context: AuthContext):
        self.calls.append(auth_context)
        if self.error is not None:
            raise self.error
        self.fence_events.append("entered")
        try:
            yield self.current
        except BaseException:
            self.fence_events.append("rolled_back")
            raise
        else:
            self.fence_events.append("committed")


class ExitFailingAuthorityReader(MutableAuthorityReader):
    @contextmanager
    def lock_current(self, *, auth_context: AuthContext):
        self.calls.append(auth_context)
        self.fence_events.append("entered")
        try:
            yield self.current
        except BaseException:
            self.fence_events.append("rollback_release_failed")
            raise RuntimeError("control fence exit failed")
        else:
            self.fence_events.append("clean_release_failed")
            raise RuntimeError("control fence exit failed")


def test_adapter_reads_current_authority_for_issue_and_verify() -> None:
    reader = MutableAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    auth_context = _auth_context()

    token = adapter.issue(auth_context=auth_context, content=_content())
    reader.current = replace(
        reader.current,
        database_now=NOW + timedelta(seconds=1),
    )
    verified = adapter.verify(auth_context=auth_context, token=token)

    assert verified.content == _content()
    assert reader.calls == [auth_context, auth_context]
    assert ROOT_KEY._material_bytes().hex() not in token


def test_require_current_exposes_no_authority_or_key_material() -> None:
    reader = MutableAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    auth_context = _auth_context()

    assert adapter.require_current(auth_context=auth_context) is None
    assert reader.calls == [auth_context]


def test_current_business_date_uses_database_time_and_tenant_timezone() -> None:
    reader = MutableAuthorityReader()
    reader.current = replace(
        reader.current,
        database_now=datetime(2026, 8, 22, 16, 30, tzinfo=timezone.utc),
    )
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    assert adapter.current_business_date(auth_context=_auth_context()) == date(
        2026, 8, 23
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"database_now": datetime(2026, 8, 22, 15, 0)},
        {"database_now": NOW.replace(microsecond=1)},
        {"tenant_timezone": ""},
        {"tenant_timezone": "Not/A_Timezone"},
    ],
)
def test_adapter_rejects_invalid_database_clock_or_tenant_timezone(changes) -> None:
    reader = MutableAuthorityReader()
    reader.current = replace(reader.current, **changes)
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    with pytest.raises(GanttPreviewAuthorityError, match="unavailable"):
        adapter.current_business_date(auth_context=_auth_context())


def test_issue_and_verify_reject_cross_business_date_content() -> None:
    reader = MutableAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    stale_content = replace(_content(), preview_date=date(2026, 8, 21))

    with pytest.raises(GanttPreviewProofError, match="invalid or stale"):
        adapter.issue(auth_context=_auth_context(), content=stale_content)

    token = adapter.issue(auth_context=_auth_context(), content=_content())
    reader.current = replace(
        reader.current,
        database_now=datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(GanttPreviewProofError, match="invalid or stale"):
        adapter.verify(auth_context=_auth_context(), token=token)


def test_verify_for_execution_holds_fence_across_caller_scope() -> None:
    reader = MutableAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    token = adapter.issue(auth_context=_auth_context(), content=_content())

    with adapter.verify_for_execution(
        auth_context=_auth_context(), token=token
    ) as verified:
        assert verified.content == _content()
        assert reader.fence_events == ["entered"]

    assert reader.fence_events == ["entered", "committed"]


def test_verify_for_execution_rolls_back_fence_and_preserves_caller_error() -> None:
    reader = MutableAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    token = adapter.issue(auth_context=_auth_context(), content=_content())

    with pytest.raises(RuntimeError, match="tenant commit failed"):
        with adapter.verify_for_execution(
            auth_context=_auth_context(), token=token
        ):
            assert reader.fence_events == ["entered"]
            raise RuntimeError("tenant commit failed")

    assert reader.fence_events == ["entered", "rolled_back"]


def test_clean_fence_release_failure_has_distinct_outcome() -> None:
    reader = ExitFailingAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    token = adapter.issue(auth_context=_auth_context(), content=_content())

    with pytest.raises(GanttPreviewFenceReleaseUncertain) as caught:
        with adapter.verify_for_execution(
            auth_context=_auth_context(), token=token
        ):
            pass

    assert str(caught.value) == (
        "Gantt preview authority fence release is uncertain"
    )
    assert reader.fence_events == ["entered", "clean_release_failed"]


def test_fence_exit_failure_does_not_mask_tenant_operation_failure() -> None:
    reader = ExitFailingAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    token = adapter.issue(auth_context=_auth_context(), content=_content())

    with pytest.raises(RuntimeError, match="tenant commit failed"):
        with adapter.verify_for_execution(
            auth_context=_auth_context(), token=token
        ):
            raise RuntimeError("tenant commit failed")

    assert reader.fence_events == ["entered", "rollback_release_failed"]


def test_verify_for_execution_releases_fence_when_proof_is_invalid() -> None:
    reader = MutableAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    with pytest.raises(GanttPreviewProofError, match="invalid or stale"):
        with adapter.verify_for_execution(
            auth_context=_auth_context(), token="not-a-proof"
        ):
            raise AssertionError("invalid proof must not reach caller scope")

    assert reader.fence_events == ["entered", "rolled_back"]


@pytest.mark.parametrize(
    "auth_context",
    [
        _auth_context(effective_gate=EffectiveTenantGate.SUSPENDED),
        _auth_context(role="operator"),
        _auth_context(session_id="not-a-uuid"),
        _auth_context(membership_id="not-a-uuid"),
        _auth_context(user_auth_version=True),
        _auth_context(tenant_access_version=0),
    ],
)
def test_adapter_rejects_non_active_or_untrusted_auth_context_before_read(
    auth_context,
) -> None:
    reader = MutableAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    with pytest.raises(GanttPreviewAuthorityError, match="unavailable"):
        adapter.issue(auth_context=auth_context, content=_content())

    assert reader.calls == []


@pytest.mark.parametrize(
    "current_authority",
    [
        _authority(
            actor_session_uuid=UUID(
                "20000000-0000-4000-8000-000000000003"
            )
        ),
        _authority(user_auth_version=5),
        _authority(tenant_access_version=9),
    ],
)
def test_adapter_rejects_current_authority_that_drifted_from_auth_context(
    current_authority,
) -> None:
    reader = MutableAuthorityReader()
    reader.current = replace(reader.current, authority=current_authority)
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    with pytest.raises(GanttPreviewAuthorityError, match="unavailable"):
        adapter.issue(auth_context=_auth_context(), content=_content())


@pytest.mark.parametrize(
    "changes",
    [
        {"session_is_current": False},
        {"effective_gate": EffectiveTenantGate.SUSPENDED},
        {"role": TenantRole.ADMIN},
        {
            "membership_uuid": UUID(
                "20000000-0000-4000-8000-000000000006"
            )
        },
    ],
)
def test_adapter_rejects_noncurrent_reader_facts(changes) -> None:
    reader = MutableAuthorityReader()
    reader.current = replace(reader.current, **changes)
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    with pytest.raises(GanttPreviewAuthorityError, match="unavailable"):
        adapter.issue(auth_context=_auth_context(), content=_content())


def test_adapter_has_no_fallback_when_current_read_fails() -> None:
    reader = MutableAuthorityReader()
    reader.error = RuntimeError("control database unavailable")
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    with pytest.raises(GanttPreviewAuthorityError) as caught:
        adapter.issue(auth_context=_auth_context(), content=_content())

    assert str(caught.value) == "current Gantt preview authority is unavailable"
    assert "control database" not in str(caught.value)


def test_adapter_requires_explicit_current_authority_port() -> None:
    with pytest.raises(TypeError, match="authority_reader"):
        GanttPreviewProofAdapter(authority_reader=object())
