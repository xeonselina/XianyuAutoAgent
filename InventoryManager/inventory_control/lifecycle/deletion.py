"""Pure tenant-deletion lifecycle reducer.

This module deliberately performs no database, provider, filesystem, or network
work.  It validates lifecycle fences and returns immutable effect facts for the
caller to persist and execute in its own transactions/workers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Optional
from uuid import UUID

from inventory_control.domain.tenant_gate import TenantStatus
from inventory_control.lifecycle.suspension import DmlLoginState, SuspensionPhase


DELETION_COOLING_PERIOD = timedelta(days=30)
_HASH_BYTES = 32
_MAX_FAILURE_CODE_LENGTH = 96
_FAILURE_CODE_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


class DeletionTransitionError(ValueError):
    """Stable, non-sensitive lifecycle failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DeletionRequestStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    COOLING_OFF = "cooling_off"
    CANCELLED = "cancelled"
    COMMITTING = "committing"
    AWAITING_OFFSITE_ACK = "awaiting_offsite_ack"
    RELEASING_CLAIMS = "releasing_claims"
    DROPPING = "dropping"
    COMPLETED = "completed"
    FAILED = "failed"


class DeletionReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class DeletionActionKind(str, Enum):
    REQUEST = "request"
    REVIEW_APPROVE = "review_approve"
    REVIEW_REJECT = "review_reject"
    CANCEL = "cancel"
    COMMIT = "commit"


class DeletionActionOutcome(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DeletionEffectKind(str, Enum):
    REVOKE_ALL_SESSIONS = "revoke_all_sessions"
    DISPOSE_TENANT_ENGINES = "dispose_tenant_engines"
    BLOCK_JOB_LEASES = "block_job_leases"
    BLOCK_PROVIDER_SUBMISSIONS = "block_provider_submissions"
    SET_DESIRED_DML_LOCKED = "set_desired_dml_locked"
    LOCK_ALL_DML_IDENTITIES = "lock_all_dml_identities"
    CREATE_DELETION_ENFORCE_LOCKED_ACTION = "create_deletion_enforce_locked_action"
    SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS = (
        "supersede_lower_priority_lifecycle_actions"
    )
    CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE = (
        "create_locked_unpublished_dml_candidate"
    )
    LOCK_UNPUBLISHED_DML_CANDIDATE = "lock_unpublished_dml_candidate"
    PUBLISH_VALIDATED_DML_CANDIDATE = "publish_validated_dml_candidate"
    RECLAIM_TENANT_JOB_LEASES = "reclaim_tenant_job_leases"
    ISOLATE_PROVIDER_OPERATIONS = "isolate_provider_operations"
    APPEND_PERMANENT_TOMBSTONE = "append_permanent_tombstone"
    REPLICATE_TOMBSTONE_OFFSITE = "replicate_tombstone_offsite"
    RECORD_VERIFIED_OFFSITE_ACK = "record_verified_offsite_ack"
    RELEASE_TENANT_PROVIDER_CLAIMS = "release_tenant_provider_claims"
    APPEND_PROVIDER_CLAIM_RELEASE_EVENTS = "append_provider_claim_release_events"
    REMOVE_TENANT_PROVIDER_ACCOUNTS_AND_BINDINGS = (
        "remove_tenant_provider_accounts_and_bindings"
    )
    REVOKE_TENANT_DATABASE_IDENTITIES = "revoke_tenant_database_identities"
    REMOVE_TENANT_DATABASE_ROUTES = "remove_tenant_database_routes"
    DROP_TENANT_SCHEMA = "drop_tenant_schema"
    MINIMIZE_TENANT_CONTROL_DATA = "minimize_tenant_control_data"
    REMOVE_TENANT_IDENTITIES_AND_RELEASE_PHONES = (
        "remove_tenant_identities_and_release_phones"
    )
    RECORD_RECOVERY_TOMBSTONED_DISPOSITIONS = (
        "record_recovery_tombstoned_dispositions"
    )
    MARK_TENANT_AND_DATABASE_UUIDS_PERMANENTLY_UNREUSABLE = (
        "mark_tenant_and_database_uuids_permanently_unreusable"
    )


@dataclass(frozen=True)
class DeletionEffectFact:
    kind: DeletionEffectKind
    request_id: UUID
    action_id: UUID
    execution_generation: int
    executor_fencing_token: int
    tenant_access_version: int
    dml_generation: Optional[int] = None
    tombstone_sequence: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DeletionEffectKind):
            _fail("INVALID_DELETION_EFFECT_KIND")
        _require_uuid("INVALID_DELETION_REQUEST_ID", self.request_id)
        _require_uuid("INVALID_DELETION_ACTION_ID", self.action_id)
        if self.execution_generation <= 0:
            _fail("INVALID_DELETION_EXECUTION_GENERATION")
        if self.executor_fencing_token <= 0:
            _fail("INVALID_DELETION_EXECUTOR_FENCING_TOKEN")
        if self.tenant_access_version <= 0:
            _fail("INVALID_TENANT_ACCESS_VERSION")
        if self.dml_generation is not None and self.dml_generation <= 0:
            _fail("INVALID_DML_GENERATION")
        if self.tombstone_sequence is not None and self.tombstone_sequence <= 0:
            _fail("INVALID_TOMBSTONE_SEQUENCE")


@dataclass(frozen=True)
class DeletionAction:
    action_id: UUID
    kind: DeletionActionKind
    execution_generation: int
    executor_fencing_token: int
    idempotency_key: str
    request_digest: bytes
    outcome: DeletionActionOutcome
    failure_code: Optional[str] = None

    def __post_init__(self) -> None:
        _require_uuid("INVALID_DELETION_ACTION_ID", self.action_id)
        if not isinstance(self.kind, DeletionActionKind):
            _fail("INVALID_DELETION_ACTION_KIND")
        if not isinstance(self.outcome, DeletionActionOutcome):
            _fail("INVALID_DELETION_ACTION_OUTCOME")
        if self.execution_generation <= 0:
            _fail("INVALID_DELETION_EXECUTION_GENERATION")
        if self.executor_fencing_token <= 0:
            _fail("INVALID_DELETION_EXECUTOR_FENCING_TOKEN")
        _require_text("INVALID_IDEMPOTENCY_KEY", self.idempotency_key, maximum=191)
        _require_digest(self.request_digest)
        if self.outcome is DeletionActionOutcome.FAILED:
            _require_failure_code(self.failure_code)
        elif self.failure_code is not None:
            _fail("UNEXPECTED_DELETION_FAILURE_CODE")


@dataclass(frozen=True)
class DeletionLifecycleContext:
    """Authoritative current-read facts supplied by the caller."""

    tenant_status: TenantStatus
    suspension_phase: Optional[SuspensionPhase]
    recovery_hold_released: bool
    subscription_expires_at_utc: datetime
    database_now_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_status, TenantStatus):
            _fail("INVALID_TENANT_STATUS")
        if self.suspension_phase is not None and not isinstance(
            self.suspension_phase, SuspensionPhase
        ):
            _fail("INVALID_SUSPENSION_PHASE")
        object.__setattr__(
            self,
            "subscription_expires_at_utc",
            _utc("INVALID_SUBSCRIPTION_EXPIRY", self.subscription_expires_at_utc),
        )
        object.__setattr__(
            self,
            "database_now_utc",
            _utc("INVALID_DATABASE_TIME", self.database_now_utc),
        )
        if not isinstance(self.recovery_hold_released, bool):
            _fail("INVALID_RECOVERY_HOLD_STATE")
        if self.tenant_status in (TenantStatus.ACTIVE, TenantStatus.EXPIRED):
            if self.suspension_phase is not None:
                _fail("INCONSISTENT_SUSPENSION_CONTEXT")
        elif self.tenant_status is TenantStatus.SUSPENDING:
            if self.suspension_phase not in (
                SuspensionPhase.FREEZING,
                SuspensionPhase.FAILED,
            ):
                _fail("INCONSISTENT_SUSPENSION_CONTEXT")
        elif self.tenant_status is TenantStatus.SUSPENDED:
            if self.suspension_phase is not SuspensionPhase.ACTIVE:
                _fail("INCONSISTENT_SUSPENSION_CONTEXT")
        elif self.tenant_status is TenantStatus.RESUMING:
            if self.suspension_phase is not SuspensionPhase.RESOLVING:
                _fail("INCONSISTENT_SUSPENSION_CONTEXT")
        else:
            _fail("INVALID_DELETION_LOWER_PRIORITY_STATE")

    @property
    def has_unresolved_suspension(self) -> bool:
        return self.suspension_phase is not None

    @property
    def realtime_subscription_status(self) -> TenantStatus:
        if self.subscription_expires_at_utc <= self.database_now_utc:
            return TenantStatus.EXPIRED
        return TenantStatus.ACTIVE

    @property
    def cancellation_status(self) -> TenantStatus:
        if self.suspension_phase is SuspensionPhase.ACTIVE:
            return TenantStatus.SUSPENDED
        if self.suspension_phase in (
            SuspensionPhase.FREEZING,
            SuspensionPhase.FAILED,
            SuspensionPhase.RESOLVING,
        ):
            return TenantStatus.SUSPENDING
        return self.realtime_subscription_status


@dataclass(frozen=True)
class DeletionTombstone:
    request_id: UUID
    tenant_id: UUID
    database_id: UUID
    sequence: int
    previous_hash: Optional[bytes]
    record_hash: bytes
    head_hash: bytes
    checkpoint_root_key_version: int
    checkpoint_mac: bytes
    recorded_at_utc: datetime

    def __post_init__(self) -> None:
        _require_uuid("INVALID_DELETION_REQUEST_ID", self.request_id)
        _require_uuid("INVALID_TENANT_ID", self.tenant_id)
        _require_uuid("INVALID_DATABASE_ID", self.database_id)
        if self.sequence <= 0:
            _fail("INVALID_TOMBSTONE_SEQUENCE")
        if self.previous_hash is not None:
            _require_hash("INVALID_TOMBSTONE_PREVIOUS_HASH", self.previous_hash)
        _require_hash("INVALID_TOMBSTONE_RECORD_HASH", self.record_hash)
        _require_hash("INVALID_TOMBSTONE_HEAD_HASH", self.head_hash)
        if self.checkpoint_root_key_version <= 0:
            _fail("INVALID_TOMBSTONE_ROOT_KEY_VERSION")
        _require_hash("INVALID_TOMBSTONE_CHECKPOINT_MAC", self.checkpoint_mac)
        object.__setattr__(
            self,
            "recorded_at_utc",
            _utc("INVALID_TOMBSTONE_TIME", self.recorded_at_utc),
        )


@dataclass(frozen=True)
class OffsiteTombstoneAck:
    sequence: int
    head_hash: bytes
    artifact_checksum: bytes
    acknowledged_at_utc: datetime
    authenticated: bool
    durably_persisted: bool
    checksum_verified: bool
    chain_verified: bool

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            _fail("INVALID_TOMBSTONE_SEQUENCE")
        _require_hash("INVALID_TOMBSTONE_HEAD_HASH", self.head_hash)
        _require_hash("INVALID_OFFSITE_ARTIFACT_CHECKSUM", self.artifact_checksum)
        object.__setattr__(
            self,
            "acknowledged_at_utc",
            _utc("INVALID_OFFSITE_ACK_TIME", self.acknowledged_at_utc),
        )
        for name in (
            "authenticated",
            "durably_persisted",
            "checksum_verified",
            "chain_verified",
        ):
            _require_bool("INVALID_OFFSITE_ACK_EVIDENCE", getattr(self, name))

    @property
    def verified(self) -> bool:
        return (
            self.authenticated
            and self.durably_persisted
            and self.checksum_verified
            and self.chain_verified
        )


@dataclass(frozen=True)
class DeletionExecutorFenceEvidence:
    action_id: UUID
    execution_generation: int
    executor_fencing_token: int
    tenant_access_version: int
    lease_fence_verified: bool

    def __post_init__(self) -> None:
        _require_uuid("INVALID_DELETION_ACTION_ID", self.action_id)
        if self.execution_generation <= 0:
            _fail("INVALID_DELETION_EXECUTION_GENERATION")
        if self.executor_fencing_token <= 0:
            _fail("INVALID_DELETION_EXECUTOR_FENCING_TOKEN")
        if self.tenant_access_version <= 0:
            _fail("INVALID_TENANT_ACCESS_VERSION")
        if not isinstance(self.lease_fence_verified, bool):
            _fail("INVALID_DELETION_LEASE_FENCE_EVIDENCE")


@dataclass(frozen=True)
class DeletionLockdownEvidence:
    action_id: UUID
    execution_generation: int
    executor_fencing_token: int
    tenant_access_version: int
    lease_fence_verified: bool
    sessions_revoked: bool
    tenant_engines_disposed: bool
    job_leases_blocked: bool
    provider_submissions_blocked: bool
    desired_dml_locked: bool
    all_dml_identities_locked: bool

    def __post_init__(self) -> None:
        _validate_executor_evidence_fields(self)
        _require_boolean_fields(
            self,
            (
                "sessions_revoked",
                "tenant_engines_disposed",
                "job_leases_blocked",
                "provider_submissions_blocked",
                "desired_dml_locked",
                "all_dml_identities_locked",
            ),
        )

    @property
    def complete(self) -> bool:
        return all(
            (
                self.sessions_revoked,
                self.lease_fence_verified,
                self.tenant_engines_disposed,
                self.job_leases_blocked,
                self.provider_submissions_blocked,
                self.desired_dml_locked,
                self.all_dml_identities_locked,
            )
        )


@dataclass(frozen=True)
class CancellationEvidence:
    action_id: UUID
    execution_generation: int
    executor_fencing_token: int
    tenant_access_version: int
    lease_fence_verified: bool
    deletion_lockdown_complete: bool
    candidate_generation: Optional[int] = None
    candidate_identity_verified: bool = False
    candidate_positive_permissions_verified: bool = False
    candidate_negative_permissions_verified: bool = False
    candidate_unpublished: bool = False

    def __post_init__(self) -> None:
        _validate_executor_evidence_fields(self)
        if self.candidate_generation is not None and self.candidate_generation <= 0:
            _fail("INVALID_CANDIDATE_DML_GENERATION")
        _require_boolean_fields(
            self,
            (
                "deletion_lockdown_complete",
                "candidate_identity_verified",
                "candidate_positive_permissions_verified",
                "candidate_negative_permissions_verified",
                "candidate_unpublished",
            ),
        )

    @property
    def candidate_complete(self) -> bool:
        return all(
            (
                self.candidate_identity_verified,
                self.candidate_positive_permissions_verified,
                self.candidate_negative_permissions_verified,
                self.candidate_unpublished,
            )
        )


@dataclass(frozen=True)
class DeletionIsolationEvidence:
    action_id: UUID
    execution_generation: int
    executor_fencing_token: int
    tenant_access_version: int
    lease_fence_verified: bool
    deletion_lockdown_complete: bool
    job_leases_reclaimed: bool
    provider_operations_isolated: bool
    all_dml_identities_locked: bool

    def __post_init__(self) -> None:
        _validate_executor_evidence_fields(self)
        _require_boolean_fields(
            self,
            (
                "deletion_lockdown_complete",
                "job_leases_reclaimed",
                "provider_operations_isolated",
                "all_dml_identities_locked",
            ),
        )

    @property
    def complete(self) -> bool:
        return all(
            (
                self.deletion_lockdown_complete,
                self.lease_fence_verified,
                self.job_leases_reclaimed,
                self.provider_operations_isolated,
                self.all_dml_identities_locked,
            )
        )


@dataclass(frozen=True)
class DeletionClaimReleaseEvidence:
    """Proof that global provider claims are safe before owner rows disappear.

    This is a durable boundary separate from destructive cleanup.  In
    particular, a caller cannot treat an emitted release effect as proof that
    the claim CAS and its append-only event actually committed.
    """

    action_id: UUID
    execution_generation: int
    executor_fencing_token: int
    tenant_access_version: int
    lease_fence_verified: bool
    tombstone_sequence: int
    tombstone_head_hash: bytes
    reserved_binding_operations_fenced: bool
    bidirectional_bindings_verified: bool
    provider_operations_isolated: bool
    claims_released_or_valid_new_owner: bool
    valid_new_owner_claims_untouched: bool
    claim_release_events_appended: bool
    no_orphan_claims: bool
    recovery_dispositions_complete: bool

    def __post_init__(self) -> None:
        _validate_executor_evidence_fields(self)
        if self.tombstone_sequence <= 0:
            _fail("INVALID_TOMBSTONE_SEQUENCE")
        _require_hash("INVALID_TOMBSTONE_HEAD_HASH", self.tombstone_head_hash)
        _require_boolean_fields(
            self,
            (
                "reserved_binding_operations_fenced",
                "bidirectional_bindings_verified",
                "provider_operations_isolated",
                "claims_released_or_valid_new_owner",
                "valid_new_owner_claims_untouched",
                "claim_release_events_appended",
                "no_orphan_claims",
                "recovery_dispositions_complete",
            ),
        )

    @property
    def complete(self) -> bool:
        return all(
            (
                self.lease_fence_verified,
                self.reserved_binding_operations_fenced,
                self.bidirectional_bindings_verified,
                self.provider_operations_isolated,
                self.claims_released_or_valid_new_owner,
                self.valid_new_owner_claims_untouched,
                self.claim_release_events_appended,
                self.no_orphan_claims,
            )
        )


@dataclass(frozen=True)
class DestructiveCleanupEvidence:
    action_id: UUID
    execution_generation: int
    executor_fencing_token: int
    tenant_access_version: int
    lease_fence_verified: bool
    tombstone_sequence: int
    tombstone_head_hash: bytes
    schema_absent: bool
    dml_identities_absent: bool
    platform_read_identities_absent: bool
    database_routes_absent: bool
    provider_accounts_and_bindings_absent: bool
    integration_secrets_absent: bool
    tenant_control_data_minimized: bool
    provider_operations_isolated: bool
    claims_released_or_valid_new_owner: bool
    no_orphan_claims: bool
    tenant_identity_removal_ready: bool
    phone_release_ready: bool
    cross_tenant_negative_checks_passed: bool
    recovery_dispositions_complete: bool

    def __post_init__(self) -> None:
        _validate_executor_evidence_fields(self)
        if self.tombstone_sequence <= 0:
            _fail("INVALID_TOMBSTONE_SEQUENCE")
        _require_hash("INVALID_TOMBSTONE_HEAD_HASH", self.tombstone_head_hash)
        _require_boolean_fields(
            self,
            (
                "schema_absent",
                "dml_identities_absent",
                "platform_read_identities_absent",
                "database_routes_absent",
                "provider_accounts_and_bindings_absent",
                "integration_secrets_absent",
                "tenant_control_data_minimized",
                "provider_operations_isolated",
                "claims_released_or_valid_new_owner",
                "no_orphan_claims",
                "tenant_identity_removal_ready",
                "phone_release_ready",
                "cross_tenant_negative_checks_passed",
                "recovery_dispositions_complete",
            ),
        )


@dataclass(frozen=True)
class DeletionRequest:
    request_id: UUID
    requested_by_user_id: UUID
    status: DeletionRequestStatus
    revision: int
    execution_generation: int
    executor_fencing_token: int
    current_action: DeletionAction
    requested_at_utc: datetime
    reviewed_by_platform_admin_id: Optional[UUID] = None
    cancelled_by_user_id: Optional[UUID] = None
    reviewed_at_utc: Optional[datetime] = None
    execute_not_before_utc: Optional[datetime] = None
    cancelled_at_utc: Optional[datetime] = None
    pre_freeze_tenant_status: Optional[TenantStatus] = None
    pre_freeze_suspension_phase: Optional[SuspensionPhase] = None
    tombstone: Optional[DeletionTombstone] = None
    offsite_ack: Optional[OffsiteTombstoneAck] = None
    failure_resume_status: Optional[DeletionRequestStatus] = None
    failure_code: Optional[str] = None

    def __post_init__(self) -> None:
        _require_uuid("INVALID_DELETION_REQUEST_ID", self.request_id)
        _require_uuid("INVALID_DELETION_REQUESTOR_ID", self.requested_by_user_id)
        if not isinstance(self.status, DeletionRequestStatus):
            _fail("INVALID_DELETION_REQUEST_STATUS")
        if self.reviewed_by_platform_admin_id is not None:
            _require_uuid(
                "INVALID_PLATFORM_REVIEWER_ID", self.reviewed_by_platform_admin_id
            )
        if self.cancelled_by_user_id is not None:
            _require_uuid("INVALID_DELETION_CANCELLER_ID", self.cancelled_by_user_id)
        if self.revision <= 0:
            _fail("INVALID_DELETION_REQUEST_REVISION")
        if self.execution_generation <= 0:
            _fail("INVALID_DELETION_EXECUTION_GENERATION")
        if self.executor_fencing_token <= 0:
            _fail("INVALID_DELETION_EXECUTOR_FENCING_TOKEN")
        if self.current_action.execution_generation != self.execution_generation:
            _fail("DELETION_ACTION_GENERATION_MISMATCH")
        if self.current_action.executor_fencing_token != self.executor_fencing_token:
            _fail("DELETION_ACTION_FENCING_TOKEN_MISMATCH")
        object.__setattr__(
            self,
            "requested_at_utc",
            _utc("INVALID_DELETION_REQUEST_TIME", self.requested_at_utc),
        )
        for name in ("reviewed_at_utc", "execute_not_before_utc", "cancelled_at_utc"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _utc("INVALID_DELETION_TIME", value))
        if self.execute_not_before_utc is not None:
            if self.reviewed_at_utc is None:
                _fail("DELETION_APPROVAL_TIME_MISSING")
            if self.execute_not_before_utc != self.reviewed_at_utc + DELETION_COOLING_PERIOD:
                _fail("INVALID_DELETION_COOLING_PERIOD")
        if self.status is DeletionRequestStatus.FAILED:
            if self.failure_resume_status not in (
                DeletionRequestStatus.COMMITTING,
                DeletionRequestStatus.AWAITING_OFFSITE_ACK,
                DeletionRequestStatus.RELEASING_CLAIMS,
                DeletionRequestStatus.DROPPING,
            ):
                _fail("INVALID_DELETION_RETRY_BOUNDARY")
            _require_failure_code(self.failure_code)
            if self.current_action.outcome is not DeletionActionOutcome.FAILED:
                _fail("DELETION_FAILED_ACTION_REQUIRED")
        elif self.failure_resume_status is not None or self.failure_code is not None:
            _fail("UNEXPECTED_DELETION_FAILURE_STATE")
        if self.status is DeletionRequestStatus.AWAITING_OFFSITE_ACK and self.tombstone is None:
            _fail("DELETION_TOMBSTONE_REQUIRED")
        if self.status in (
            DeletionRequestStatus.RELEASING_CLAIMS,
            DeletionRequestStatus.DROPPING,
            DeletionRequestStatus.COMPLETED,
        ):
            if self.tombstone is None or self.offsite_ack is None:
                _fail("VERIFIED_OFFSITE_TOMBSTONE_REQUIRED")
            if not self.offsite_ack.verified:
                _fail("VERIFIED_OFFSITE_TOMBSTONE_REQUIRED")
        if self.offsite_ack is not None:
            if self.tombstone is None:
                _fail("DELETION_TOMBSTONE_REQUIRED")
            if (
                self.offsite_ack.sequence != self.tombstone.sequence
                or self.offsite_ack.head_hash != self.tombstone.head_hash
            ):
                _fail("OFFSITE_TOMBSTONE_ACK_MISMATCH")


@dataclass(frozen=True)
class DeletionState:
    tenant_id: UUID
    database_id: UUID
    tenant_status: TenantStatus
    tenant_access_version: int
    desired_dml_login_state: DmlLoginState
    published_dml_generation: int
    latest_dml_generation: int
    candidate_dml_generation: Optional[int]
    request: Optional[DeletionRequest] = None
    recovery_dispositions_required: bool = False

    def __post_init__(self) -> None:
        _require_uuid("INVALID_TENANT_ID", self.tenant_id)
        _require_uuid("INVALID_DATABASE_ID", self.database_id)
        if not isinstance(self.tenant_status, TenantStatus):
            _fail("INVALID_TENANT_STATUS")
        if not isinstance(self.desired_dml_login_state, DmlLoginState):
            _fail("INVALID_DML_LOGIN_STATE")
        if self.tenant_access_version <= 0:
            _fail("INVALID_TENANT_ACCESS_VERSION")
        if self.published_dml_generation <= 0:
            _fail("INVALID_DML_GENERATION")
        if self.latest_dml_generation < self.published_dml_generation:
            _fail("INVALID_DML_GENERATION_ORDER")
        if self.candidate_dml_generation is not None:
            if self.candidate_dml_generation <= self.latest_dml_generation:
                _fail("INVALID_CANDIDATE_DML_GENERATION")
        if not isinstance(self.recovery_dispositions_required, bool):
            _fail("INVALID_RECOVERY_DISPOSITION_REQUIREMENT")
        if self.request is None:
            if self.tenant_status in (
                TenantStatus.DELETION_COOLING_OFF,
                TenantStatus.DELETION_COMMITTING,
                TenantStatus.DELETED,
            ):
                _fail("DELETION_REQUEST_REQUIRED")
            return
        request = self.request
        if request.tombstone is not None:
            if (
                request.tombstone.tenant_id != self.tenant_id
                or request.tombstone.database_id != self.database_id
                or request.tombstone.request_id != request.request_id
            ):
                _fail("TOMBSTONE_SCOPE_MISMATCH")
        if request.status is DeletionRequestStatus.COOLING_OFF:
            if self.tenant_status is not TenantStatus.DELETION_COOLING_OFF:
                _fail("DELETION_STATE_PROJECTION_MISMATCH")
            if self.desired_dml_login_state is not DmlLoginState.LOCKED:
                _fail("DELETION_DML_MUST_REMAIN_LOCKED")
        elif request.status in (
            DeletionRequestStatus.COMMITTING,
            DeletionRequestStatus.AWAITING_OFFSITE_ACK,
            DeletionRequestStatus.RELEASING_CLAIMS,
            DeletionRequestStatus.DROPPING,
        ):
            if self.tenant_status is not TenantStatus.DELETION_COMMITTING:
                _fail("DELETION_STATE_PROJECTION_MISMATCH")
            if self.desired_dml_login_state is not DmlLoginState.LOCKED:
                _fail("DELETION_DML_MUST_REMAIN_LOCKED")
        elif request.status is DeletionRequestStatus.FAILED:
            if self.tenant_status is not TenantStatus.DELETION_COMMITTING:
                _fail("DELETION_STATE_PROJECTION_MISMATCH")
            if self.desired_dml_login_state is not DmlLoginState.LOCKED:
                _fail("DELETION_DML_MUST_REMAIN_LOCKED")
        elif request.status is DeletionRequestStatus.COMPLETED:
            if self.tenant_status is not TenantStatus.DELETED:
                _fail("DELETION_STATE_PROJECTION_MISMATCH")
            if self.desired_dml_login_state is not DmlLoginState.LOCKED:
                _fail("DELETION_DML_MUST_REMAIN_LOCKED")
        else:
            if self.tenant_status in (
                TenantStatus.DELETION_COOLING_OFF,
                TenantStatus.DELETION_COMMITTING,
                TenantStatus.DELETED,
            ):
                _fail("DELETION_STATE_PROJECTION_MISMATCH")

    @classmethod
    def eligible(
        cls,
        *,
        tenant_id: UUID,
        database_id: UUID,
        tenant_status: TenantStatus = TenantStatus.ACTIVE,
        tenant_access_version: int = 1,
        published_dml_generation: int = 1,
        latest_dml_generation: Optional[int] = None,
        recovery_dispositions_required: bool = False,
    ) -> "DeletionState":
        if latest_dml_generation is None:
            latest_dml_generation = published_dml_generation
        desired = (
            DmlLoginState.ACTIVE
            if tenant_status in (TenantStatus.ACTIVE, TenantStatus.EXPIRED)
            else DmlLoginState.LOCKED
        )
        return cls(
            tenant_id=tenant_id,
            database_id=database_id,
            tenant_status=tenant_status,
            tenant_access_version=tenant_access_version,
            desired_dml_login_state=desired,
            published_dml_generation=published_dml_generation,
            latest_dml_generation=latest_dml_generation,
            candidate_dml_generation=None,
            recovery_dispositions_required=recovery_dispositions_required,
        )


@dataclass(frozen=True)
class DeletionTransition:
    state: DeletionState
    effects: tuple[DeletionEffectFact, ...]
    idempotent_replay: bool = False
    subscription_expiry_changed: bool = False
    service_time_compensated: bool = False
    redemption_code_consumed: bool = False
    external_side_effect_performed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.state, DeletionState):
            _fail("INVALID_DELETION_STATE")
        if not isinstance(self.effects, tuple) or not all(
            isinstance(effect, DeletionEffectFact) for effect in self.effects
        ):
            _fail("INVALID_DELETION_EFFECT_FACTS")


def request_deletion(
    state: DeletionState,
    *,
    context: DeletionLifecycleContext,
    request_id: UUID,
    action_id: UUID,
    requested_by_user_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    requested_at_utc: datetime,
    actor_is_active_admin: bool,
    purpose_bound_otp_verified: bool,
    expected_access_version: int,
) -> DeletionTransition:
    """Create the sole non-terminal deletion request without changing access."""

    _validate_new_action(action_id, idempotency_key, request_digest)
    _require_uuid("INVALID_DELETION_REQUEST_ID", request_id)
    _require_uuid("INVALID_DELETION_REQUESTOR_ID", requested_by_user_id)
    requested_at_utc = _utc("INVALID_DELETION_REQUEST_TIME", requested_at_utc)
    if state.request is not None:
        replay = _action_replay(
            state,
            action_id=action_id,
            kind=DeletionActionKind.REQUEST,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
        )
        if replay:
            return _transition(state, idempotent_replay=True)
        if state.request.status not in (
            DeletionRequestStatus.REJECTED,
            DeletionRequestStatus.CANCELLED,
        ):
            _fail("ACTIVE_DELETION_REQUEST_EXISTS")
    _expect_access(state, expected_access_version)
    if actor_is_active_admin is not True:
        _fail("DELETION_ACTIVE_ADMIN_REQUIRED")
    if purpose_bound_otp_verified is not True:
        _fail("DELETION_PURPOSE_BOUND_OTP_REQUIRED")
    if (
        context.tenant_status is not TenantStatus.ACTIVE
        or context.realtime_subscription_status is not TenantStatus.ACTIVE
        or context.has_unresolved_suspension
        or not context.recovery_hold_released
    ):
        _fail("TENANT_DELETION_REQUEST_NOT_ALLOWED")
    if state.tenant_status != context.tenant_status:
        _fail("STALE_DELETION_LIFECYCLE_CONTEXT")
    action = DeletionAction(
        action_id=action_id,
        kind=DeletionActionKind.REQUEST,
        execution_generation=1,
        executor_fencing_token=1,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        outcome=DeletionActionOutcome.SUCCEEDED,
    )
    request = DeletionRequest(
        request_id=request_id,
        requested_by_user_id=requested_by_user_id,
        status=DeletionRequestStatus.PENDING_REVIEW,
        revision=1,
        execution_generation=1,
        executor_fencing_token=1,
        current_action=action,
        requested_at_utc=requested_at_utc,
    )
    return _transition(replace(state, request=request))


def review_deletion(
    state: DeletionState,
    *,
    context: DeletionLifecycleContext,
    decision: DeletionReviewDecision,
    action_id: UUID,
    platform_reviewer_id: UUID,
    reviewer_is_active_platform_admin: bool,
    idempotency_key: str,
    request_digest: bytes,
    reviewed_at_utc: datetime,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
) -> DeletionTransition:
    """Reject a request or approve it and immediately install the deny overlay."""

    _validate_new_action(action_id, idempotency_key, request_digest)
    _require_uuid("INVALID_PLATFORM_REVIEWER_ID", platform_reviewer_id)
    reviewed_at_utc = _utc("INVALID_DELETION_REVIEW_TIME", reviewed_at_utc)
    if not isinstance(decision, DeletionReviewDecision):
        _fail("INVALID_DELETION_REVIEW_DECISION")
    kind = (
        DeletionActionKind.REVIEW_APPROVE
        if decision is DeletionReviewDecision.APPROVE
        else DeletionActionKind.REVIEW_REJECT
    )
    if _action_replay(
        state,
        action_id=action_id,
        kind=kind,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    ):
        return _transition(state, idempotent_replay=True)
    if reviewer_is_active_platform_admin is not True:
        _fail("DELETION_PLATFORM_REVIEWER_REQUIRED")
    request = _require_request(state)
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if request.status is not DeletionRequestStatus.PENDING_REVIEW:
        _fail("DELETION_REQUEST_NOT_PENDING_REVIEW")
    generation = request.execution_generation + 1
    fencing_token = request.executor_fencing_token + 1
    if decision is DeletionReviewDecision.REJECT:
        action = DeletionAction(
            action_id=action_id,
            kind=kind,
            execution_generation=generation,
            executor_fencing_token=fencing_token,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            outcome=DeletionActionOutcome.SUCCEEDED,
        )
        new_request = replace(
            request,
            status=DeletionRequestStatus.REJECTED,
            revision=request.revision + 1,
            execution_generation=generation,
            executor_fencing_token=fencing_token,
            current_action=action,
            reviewed_at_utc=reviewed_at_utc,
            reviewed_by_platform_admin_id=platform_reviewer_id,
        )
        return _transition(replace(state, request=new_request))
    if decision is not DeletionReviewDecision.APPROVE:
        _fail("INVALID_DELETION_REVIEW_DECISION")
    action = DeletionAction(
        action_id=action_id,
        kind=kind,
        execution_generation=generation,
        executor_fencing_token=fencing_token,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        outcome=DeletionActionOutcome.RUNNING,
    )
    access_version = state.tenant_access_version + 1
    new_request = replace(
        request,
        status=DeletionRequestStatus.COOLING_OFF,
        revision=request.revision + 1,
        execution_generation=generation,
        executor_fencing_token=fencing_token,
        current_action=action,
        reviewed_at_utc=reviewed_at_utc,
        reviewed_by_platform_admin_id=platform_reviewer_id,
        execute_not_before_utc=reviewed_at_utc + DELETION_COOLING_PERIOD,
        pre_freeze_tenant_status=context.tenant_status,
        pre_freeze_suspension_phase=context.suspension_phase,
    )
    new_state = replace(
        state,
        tenant_status=TenantStatus.DELETION_COOLING_OFF,
        tenant_access_version=access_version,
        desired_dml_login_state=DmlLoginState.LOCKED,
        candidate_dml_generation=None,
        request=new_request,
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            (
                DeletionEffectKind.REVOKE_ALL_SESSIONS,
                DeletionEffectKind.DISPOSE_TENANT_ENGINES,
                DeletionEffectKind.BLOCK_JOB_LEASES,
                DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
                DeletionEffectKind.SET_DESIRED_DML_LOCKED,
                DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
                DeletionEffectKind.CREATE_DELETION_ENFORCE_LOCKED_ACTION,
                DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS,
            ),
        ),
    )


def complete_approval_lockdown(
    state: DeletionState,
    *,
    evidence: DeletionLockdownEvidence,
    expected_request_revision: int,
) -> DeletionTransition:
    request = _require_request(state)
    if (
        request.status is DeletionRequestStatus.COOLING_OFF
        and request.current_action.kind is DeletionActionKind.REVIEW_APPROVE
        and request.current_action.outcome is DeletionActionOutcome.SUCCEEDED
    ):
        return _transition(state, idempotent_replay=True)
    if request.status is not DeletionRequestStatus.COOLING_OFF:
        _fail("DELETION_NOT_IN_COOLING_OFF")
    if request.current_action.kind is not DeletionActionKind.REVIEW_APPROVE:
        _fail("DELETION_APPROVAL_ACTION_NOT_CURRENT")
    _expect_request_revision(request, expected_request_revision)
    _validate_lockdown_evidence(state, request, evidence)
    if not evidence.complete:
        _fail("DELETION_LOCKDOWN_BARRIER_INCOMPLETE")
    action = replace(
        request.current_action,
        outcome=DeletionActionOutcome.SUCCEEDED,
        failure_code=None,
    )
    return _transition(
        replace(
            state,
            request=replace(request, current_action=action, revision=request.revision + 1),
        )
    )


def fail_cooling_action(
    state: DeletionState,
    *,
    failure_code: str,
    action_id: UUID,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
) -> DeletionTransition:
    """Record a retryable cooling/cancellation failure without relaxing deny."""

    _require_failure_code(failure_code)
    request = _require_request(state)
    if (
        request.status is DeletionRequestStatus.COOLING_OFF
        and request.current_action.action_id == action_id
        and request.current_action.outcome is DeletionActionOutcome.FAILED
        and request.current_action.failure_code == failure_code
    ):
        return _transition(state, idempotent_replay=True)
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if request.status is not DeletionRequestStatus.COOLING_OFF:
        _fail("DELETION_NOT_IN_COOLING_OFF")
    if request.current_action.action_id != action_id:
        _fail("DELETION_ACTION_CONFLICT")
    if request.current_action.kind not in (
        DeletionActionKind.REVIEW_APPROVE,
        DeletionActionKind.CANCEL,
    ):
        _fail("DELETION_ACTION_NOT_RETRYABLE")
    if request.current_action.outcome is DeletionActionOutcome.SUCCEEDED:
        _fail("DELETION_ACTION_ALREADY_COMPLETED")
    action = replace(
        request.current_action,
        outcome=DeletionActionOutcome.FAILED,
        failure_code=failure_code,
    )
    new_state = replace(
        state,
        request=replace(request, current_action=action, revision=request.revision + 1),
    )
    effects = [
        DeletionEffectKind.BLOCK_JOB_LEASES,
        DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
        DeletionEffectKind.SET_DESIRED_DML_LOCKED,
        DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
    ]
    if state.candidate_dml_generation is not None:
        effects.append(DeletionEffectKind.LOCK_UNPUBLISHED_DML_CANDIDATE)
    return _transition(new_state, effects=_facts(new_state, effects))


def request_deletion_cancellation(
    state: DeletionState,
    *,
    context: DeletionLifecycleContext,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    cancelled_by_user_id: UUID,
    actor_is_active_admin: bool,
    purpose_bound_otp_verified: bool,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
) -> DeletionTransition:
    """Create a cancellation action while leaving the deletion overlay locked."""

    _validate_new_action(action_id, idempotency_key, request_digest)
    _require_uuid("INVALID_DELETION_CANCELLER_ID", cancelled_by_user_id)
    if _action_replay(
        state,
        action_id=action_id,
        kind=DeletionActionKind.CANCEL,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    ):
        return _transition(state, idempotent_replay=True)
    request = _require_request(state)
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if request.status is not DeletionRequestStatus.COOLING_OFF:
        _fail("DELETION_NOT_IN_COOLING_OFF")
    if (
        request.current_action.kind is not DeletionActionKind.REVIEW_APPROVE
        or request.current_action.outcome is not DeletionActionOutcome.SUCCEEDED
    ):
        _fail("DELETION_LOCKDOWN_BARRIER_INCOMPLETE")
    if actor_is_active_admin is not True:
        _fail("DELETION_CANCEL_ACTIVE_ADMIN_REQUIRED")
    if purpose_bound_otp_verified is not True:
        _fail("DELETION_CANCEL_PURPOSE_BOUND_OTP_REQUIRED")
    _require_cooling_window_open(request, context.database_now_utc)
    generation = request.execution_generation + 1
    fencing_token = request.executor_fencing_token + 1
    candidate = None
    effects = [
        DeletionEffectKind.BLOCK_JOB_LEASES,
        DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
        DeletionEffectKind.SET_DESIRED_DML_LOCKED,
        DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
    ]
    latest = state.latest_dml_generation
    if context.recovery_hold_released and not context.has_unresolved_suspension:
        candidate = latest + 1
        effects.append(DeletionEffectKind.CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE)
    action = DeletionAction(
        action_id=action_id,
        kind=DeletionActionKind.CANCEL,
        execution_generation=generation,
        executor_fencing_token=fencing_token,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        outcome=DeletionActionOutcome.RUNNING,
    )
    new_state = replace(
        state,
        candidate_dml_generation=candidate,
        request=replace(
            request,
            revision=request.revision + 1,
            execution_generation=generation,
            executor_fencing_token=fencing_token,
            current_action=action,
            cancelled_by_user_id=cancelled_by_user_id,
        ),
    )
    return _transition(new_state, effects=_facts(new_state, effects))


def complete_deletion_cancellation(
    state: DeletionState,
    *,
    context: DeletionLifecycleContext,
    evidence: CancellationEvidence,
    expected_request_revision: int,
) -> DeletionTransition:
    """Remove the overlay only after current-read gates and candidate checks."""

    request = _require_request(state)
    if (
        request.status is DeletionRequestStatus.CANCELLED
        and request.current_action.kind is DeletionActionKind.CANCEL
        and request.current_action.outcome is DeletionActionOutcome.SUCCEEDED
    ):
        return _transition(state, idempotent_replay=True)
    if request.status is not DeletionRequestStatus.COOLING_OFF:
        _fail("DELETION_NOT_IN_COOLING_OFF")
    if request.current_action.kind is not DeletionActionKind.CANCEL:
        _fail("DELETION_CANCELLATION_ACTION_NOT_CURRENT")
    _expect_request_revision(request, expected_request_revision)
    _require_cooling_window_open(request, context.database_now_utc)
    _validate_action_evidence(state, request, evidence)
    if not evidence.deletion_lockdown_complete:
        _fail("DELETION_LOCKDOWN_BARRIER_INCOMPLETE")
    can_publish = context.recovery_hold_released and not context.has_unresolved_suspension
    effects: list[DeletionEffectKind]
    published = state.published_dml_generation
    latest = state.latest_dml_generation
    desired = DmlLoginState.LOCKED
    if can_publish:
        candidate = state.candidate_dml_generation
        if candidate is None:
            _fail("CANCELLATION_CANDIDATE_REQUIRED")
        if evidence.candidate_generation != candidate:
            _fail("STALE_CANCELLATION_CANDIDATE")
        if not evidence.candidate_complete:
            _fail("CANCELLATION_CANDIDATE_VALIDATION_INCOMPLETE")
        published = candidate
        latest = candidate
        desired = DmlLoginState.ACTIVE
        effects = [
            DeletionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE,
            DeletionEffectKind.DISPOSE_TENANT_ENGINES,
            DeletionEffectKind.REVOKE_ALL_SESSIONS,
        ]
    else:
        effects = [
            DeletionEffectKind.BLOCK_JOB_LEASES,
            DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            DeletionEffectKind.SET_DESIRED_DML_LOCKED,
            DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
        ]
        if state.candidate_dml_generation is not None:
            effects.append(DeletionEffectKind.LOCK_UNPUBLISHED_DML_CANDIDATE)
            latest = max(latest, state.candidate_dml_generation)
    action = replace(
        request.current_action,
        outcome=DeletionActionOutcome.SUCCEEDED,
        failure_code=None,
    )
    new_state = replace(
        state,
        tenant_status=context.cancellation_status,
        desired_dml_login_state=desired,
        published_dml_generation=published,
        latest_dml_generation=latest,
        candidate_dml_generation=None,
        request=replace(
            request,
            status=DeletionRequestStatus.CANCELLED,
            revision=request.revision + 1,
            current_action=action,
            cancelled_at_utc=context.database_now_utc,
        ),
    )
    return _transition(new_state, effects=_facts(new_state, effects))


def begin_deletion_commit(
    state: DeletionState,
    *,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    database_now_utc: datetime,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
    lease_fence_verified: bool,
) -> DeletionTransition:
    """Cross the irreversible boundary at or after the exact 30-day deadline."""

    _validate_new_action(action_id, idempotency_key, request_digest)
    database_now_utc = _utc("INVALID_DATABASE_TIME", database_now_utc)
    if _action_replay(
        state,
        action_id=action_id,
        kind=DeletionActionKind.COMMIT,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    ):
        return _transition(state, idempotent_replay=True)
    request = _require_request(state)
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if lease_fence_verified is not True:
        _fail("DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED")
    if request.status is not DeletionRequestStatus.COOLING_OFF:
        _fail("DELETION_NOT_IN_COOLING_OFF")
    if (
        request.current_action.kind is not DeletionActionKind.REVIEW_APPROVE
        or request.current_action.outcome is not DeletionActionOutcome.SUCCEEDED
    ):
        _fail("DELETION_LOCKDOWN_BARRIER_INCOMPLETE")
    if request.execute_not_before_utc is None:
        _fail("DELETION_APPROVAL_TIME_MISSING")
    if database_now_utc < request.execute_not_before_utc:
        _fail("DELETION_COOLING_PERIOD_NOT_ELAPSED")
    generation = request.execution_generation + 1
    fencing_token = request.executor_fencing_token + 1
    access_version = state.tenant_access_version + 1
    action = DeletionAction(
        action_id=action_id,
        kind=DeletionActionKind.COMMIT,
        execution_generation=generation,
        executor_fencing_token=fencing_token,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        outcome=DeletionActionOutcome.RUNNING,
    )
    new_state = replace(
        state,
        tenant_status=TenantStatus.DELETION_COMMITTING,
        tenant_access_version=access_version,
        desired_dml_login_state=DmlLoginState.LOCKED,
        candidate_dml_generation=None,
        request=replace(
            request,
            status=DeletionRequestStatus.COMMITTING,
            revision=request.revision + 1,
            execution_generation=generation,
            executor_fencing_token=fencing_token,
            current_action=action,
        ),
    )
    return _transition(
        new_state,
        effects=_facts(new_state, _commit_isolation_effects()),
    )


def record_permanent_tombstone(
    state: DeletionState,
    *,
    tombstone: DeletionTombstone,
    evidence: DeletionIsolationEvidence,
    expected_request_revision: int,
) -> DeletionTransition:
    """Atomically record a privacy-minimized tombstone before any cleanup."""

    request = _require_request(state)
    if request.tombstone is not None:
        if request.tombstone == tombstone and request.status in (
            DeletionRequestStatus.AWAITING_OFFSITE_ACK,
            DeletionRequestStatus.DROPPING,
            DeletionRequestStatus.COMPLETED,
        ):
            return _transition(state, idempotent_replay=True)
        _fail("DELETION_TOMBSTONE_CONFLICT")
    _expect_request_revision(request, expected_request_revision)
    if request.status is not DeletionRequestStatus.COMMITTING:
        _fail("DELETION_NOT_COMMITTING")
    if request.current_action.kind is not DeletionActionKind.COMMIT:
        _fail("DELETION_COMMIT_ACTION_NOT_CURRENT")
    _validate_action_evidence(state, request, evidence)
    if not evidence.complete:
        _fail("DELETION_ISOLATION_BARRIER_INCOMPLETE")
    if (
        tombstone.request_id != request.request_id
        or tombstone.tenant_id != state.tenant_id
        or tombstone.database_id != state.database_id
    ):
        _fail("TOMBSTONE_SCOPE_MISMATCH")
    new_state = replace(
        state,
        request=replace(
            request,
            status=DeletionRequestStatus.AWAITING_OFFSITE_ACK,
            revision=request.revision + 1,
            tombstone=tombstone,
        ),
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            (
                DeletionEffectKind.APPEND_PERMANENT_TOMBSTONE,
                DeletionEffectKind.REPLICATE_TOMBSTONE_OFFSITE,
            ),
            tombstone_sequence=tombstone.sequence,
        ),
    )


def confirm_offsite_tombstone(
    state: DeletionState,
    *,
    acknowledgment: OffsiteTombstoneAck,
    executor_fence: DeletionExecutorFenceEvidence,
    expected_request_revision: int,
) -> DeletionTransition:
    """Record a matching authenticated durable offsite acknowledgment."""

    request = _require_request(state)
    if request.offsite_ack is not None:
        if request.offsite_ack == acknowledgment:
            return _transition(state, idempotent_replay=True)
        _fail("OFFSITE_TOMBSTONE_ACK_CONFLICT")
    _expect_request_revision(request, expected_request_revision)
    if request.status is not DeletionRequestStatus.AWAITING_OFFSITE_ACK:
        _fail("DELETION_NOT_AWAITING_OFFSITE_ACK")
    _validate_action_evidence(state, request, executor_fence)
    tombstone = request.tombstone
    if tombstone is None:
        _fail("DELETION_TOMBSTONE_REQUIRED")
    if not acknowledgment.verified:
        _fail("OFFSITE_TOMBSTONE_ACK_NOT_VERIFIED")
    if (
        acknowledgment.sequence != tombstone.sequence
        or acknowledgment.head_hash != tombstone.head_hash
    ):
        _fail("OFFSITE_TOMBSTONE_ACK_MISMATCH")
    new_state = replace(
        state,
        request=replace(
            request,
            revision=request.revision + 1,
            offsite_ack=acknowledgment,
        ),
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            (DeletionEffectKind.RECORD_VERIFIED_OFFSITE_ACK,),
            tombstone_sequence=tombstone.sequence,
        ),
    )


def begin_provider_claim_release(
    state: DeletionState,
    *,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
    lease_fence_verified: bool,
) -> DeletionTransition:
    """Enter the durable provider-claim barrier after verified offsite ack.

    No database account, route, schema, provider account, binding, credential,
    or tenant identity removal is emitted from this transition.  Those effects
    become eligible only after current claim ownership and append-only release
    events have been evidenced in a later control-plane transaction.
    """

    request = _require_request(state)
    if request.status in (
        DeletionRequestStatus.RELEASING_CLAIMS,
        DeletionRequestStatus.DROPPING,
        DeletionRequestStatus.COMPLETED,
    ):
        return _transition(state, idempotent_replay=True)
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if lease_fence_verified is not True:
        _fail("DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED")
    if request.status is not DeletionRequestStatus.AWAITING_OFFSITE_ACK:
        _fail("DELETION_NOT_AWAITING_OFFSITE_ACK")
    tombstone = request.tombstone
    ack = request.offsite_ack
    if tombstone is None or ack is None or not ack.verified:
        _fail("VERIFIED_OFFSITE_TOMBSTONE_REQUIRED")
    if ack.sequence != tombstone.sequence or ack.head_hash != tombstone.head_hash:
        _fail("OFFSITE_TOMBSTONE_ACK_MISMATCH")
    new_state = replace(
        state,
        request=replace(
            request,
            status=DeletionRequestStatus.RELEASING_CLAIMS,
            revision=request.revision + 1,
        ),
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            _claim_release_effects(new_state.recovery_dispositions_required),
            tombstone_sequence=tombstone.sequence,
        ),
    )


def begin_destructive_cleanup(
    state: DeletionState,
    *,
    evidence: DeletionClaimReleaseEvidence,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
    lease_fence_verified: bool,
) -> DeletionTransition:
    """Emit destructive work only after the claim-release barrier commits."""

    request = _require_request(state)
    if request.status in (
        DeletionRequestStatus.DROPPING,
        DeletionRequestStatus.COMPLETED,
    ):
        return _transition(state, idempotent_replay=True)
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if lease_fence_verified is not True:
        _fail("DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED")
    if request.status is not DeletionRequestStatus.RELEASING_CLAIMS:
        _fail("DELETION_NOT_RELEASING_CLAIMS")
    _validate_action_evidence(state, request, evidence)
    if not evidence.complete:
        _fail("DELETION_CLAIM_RELEASE_BARRIER_INCOMPLETE")
    tombstone = request.tombstone
    ack = request.offsite_ack
    if tombstone is None or ack is None or not ack.verified:
        _fail("VERIFIED_OFFSITE_TOMBSTONE_REQUIRED")
    if ack.sequence != tombstone.sequence or ack.head_hash != tombstone.head_hash:
        _fail("OFFSITE_TOMBSTONE_ACK_MISMATCH")
    if (
        evidence.tombstone_sequence != tombstone.sequence
        or evidence.tombstone_head_hash != tombstone.head_hash
    ):
        _fail("DELETION_CLAIM_RELEASE_TOMBSTONE_MISMATCH")
    if (
        state.recovery_dispositions_required
        and not evidence.recovery_dispositions_complete
    ):
        _fail("DELETION_RECOVERY_DISPOSITIONS_INCOMPLETE")
    new_state = replace(
        state,
        request=replace(
            request,
            status=DeletionRequestStatus.DROPPING,
            revision=request.revision + 1,
        ),
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            _destructive_cleanup_effects(),
            tombstone_sequence=tombstone.sequence,
        ),
    )


def complete_deletion(
    state: DeletionState,
    *,
    evidence: DestructiveCleanupEvidence,
    expected_request_revision: int,
) -> DeletionTransition:
    """Return the final control transaction after all cleanup proofs pass.

    The identity/phone effect fact must be applied atomically with the returned
    ``COMPLETED`` state.  This prevents a phone from becoming claimable while a
    deletion is still pending, dropping, or failed.
    """

    request = _require_request(state)
    if request.status is DeletionRequestStatus.COMPLETED:
        return _transition(state, idempotent_replay=True)
    _expect_request_revision(request, expected_request_revision)
    if request.status is not DeletionRequestStatus.DROPPING:
        _fail("DELETION_NOT_DROPPING")
    _validate_action_evidence(state, request, evidence)
    tombstone = request.tombstone
    if tombstone is None or request.offsite_ack is None:
        _fail("VERIFIED_OFFSITE_TOMBSTONE_REQUIRED")
    if (
        evidence.tombstone_sequence != tombstone.sequence
        or evidence.tombstone_head_hash != tombstone.head_hash
    ):
        _fail("DELETION_COMPLETION_TOMBSTONE_MISMATCH")
    required = (
        evidence.schema_absent,
        evidence.dml_identities_absent,
        evidence.platform_read_identities_absent,
        evidence.database_routes_absent,
        evidence.provider_accounts_and_bindings_absent,
        evidence.integration_secrets_absent,
        evidence.tenant_control_data_minimized,
        evidence.provider_operations_isolated,
        evidence.claims_released_or_valid_new_owner,
        evidence.no_orphan_claims,
        evidence.tenant_identity_removal_ready,
        evidence.phone_release_ready,
        evidence.cross_tenant_negative_checks_passed,
    )
    if not all(required):
        _fail("DELETION_CLEANUP_EVIDENCE_INCOMPLETE")
    if state.recovery_dispositions_required and not evidence.recovery_dispositions_complete:
        _fail("DELETION_RECOVERY_DISPOSITIONS_INCOMPLETE")
    action = replace(
        request.current_action,
        outcome=DeletionActionOutcome.SUCCEEDED,
        failure_code=None,
    )
    new_state = replace(
        state,
        tenant_status=TenantStatus.DELETED,
        desired_dml_login_state=DmlLoginState.LOCKED,
        request=replace(
            request,
            status=DeletionRequestStatus.COMPLETED,
            revision=request.revision + 1,
            current_action=action,
        ),
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            (
                DeletionEffectKind.REMOVE_TENANT_IDENTITIES_AND_RELEASE_PHONES,
                DeletionEffectKind.MARK_TENANT_AND_DATABASE_UUIDS_PERMANENTLY_UNREUSABLE,
            ),
            tombstone_sequence=tombstone.sequence,
        ),
    )


def fail_irreversible_deletion_step(
    state: DeletionState,
    *,
    failure_code: str,
    action_id: UUID,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
    lease_fence_verified: bool,
) -> DeletionTransition:
    """Persist a non-sensitive failure while keeping deletion priority and deny."""

    _require_failure_code(failure_code)
    request = _require_request(state)
    if request.status is DeletionRequestStatus.FAILED:
        if (
            request.current_action.action_id == action_id
            and request.failure_code == failure_code
        ):
            return _transition(state, idempotent_replay=True)
        _fail("DELETION_FAILURE_CONFLICT")
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if lease_fence_verified is not True:
        _fail("DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED")
    if request.status not in (
        DeletionRequestStatus.COMMITTING,
        DeletionRequestStatus.AWAITING_OFFSITE_ACK,
        DeletionRequestStatus.RELEASING_CLAIMS,
        DeletionRequestStatus.DROPPING,
    ):
        _fail("DELETION_IRREVERSIBLE_STEP_NOT_RUNNING")
    if request.current_action.kind is not DeletionActionKind.COMMIT:
        _fail("DELETION_COMMIT_ACTION_NOT_CURRENT")
    if request.current_action.action_id != action_id:
        _fail("DELETION_ACTION_CONFLICT")
    action = replace(
        request.current_action,
        outcome=DeletionActionOutcome.FAILED,
        failure_code=failure_code,
    )
    new_state = replace(
        state,
        tenant_status=TenantStatus.DELETION_COMMITTING,
        desired_dml_login_state=DmlLoginState.LOCKED,
        request=replace(
            request,
            status=DeletionRequestStatus.FAILED,
            revision=request.revision + 1,
            current_action=action,
            failure_resume_status=request.status,
            failure_code=failure_code,
        ),
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            (
                DeletionEffectKind.BLOCK_JOB_LEASES,
                DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
                DeletionEffectKind.SET_DESIRED_DML_LOCKED,
                DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
            ),
        ),
    )


def retry_failed_deletion(
    state: DeletionState,
    *,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
    lease_fence_verified: bool,
) -> DeletionTransition:
    """Fence the failed executor and resume from the completed boundary."""

    _validate_new_action(action_id, idempotency_key, request_digest)
    request = _require_request(state)
    _expect_fences(
        state,
        request,
        expected_request_revision=expected_request_revision,
        expected_access_version=expected_access_version,
        expected_execution_generation=expected_execution_generation,
        expected_executor_fencing_token=expected_executor_fencing_token,
    )
    if lease_fence_verified is not True:
        _fail("DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED")
    if request.status is not DeletionRequestStatus.FAILED:
        _fail("DELETION_NOT_FAILED")
    if request.current_action.action_id != action_id:
        _fail("DELETION_RETRY_ACTION_MISMATCH")
    _verify_action_identity(
        request.current_action,
        kind=DeletionActionKind.COMMIT,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    resume_status = request.failure_resume_status
    if resume_status not in (
        DeletionRequestStatus.COMMITTING,
        DeletionRequestStatus.AWAITING_OFFSITE_ACK,
        DeletionRequestStatus.RELEASING_CLAIMS,
        DeletionRequestStatus.DROPPING,
    ):
        _fail("INVALID_DELETION_RETRY_BOUNDARY")
    generation = request.execution_generation + 1
    fencing_token = request.executor_fencing_token + 1
    action = replace(
        request.current_action,
        execution_generation=generation,
        executor_fencing_token=fencing_token,
        outcome=DeletionActionOutcome.RUNNING,
        failure_code=None,
    )
    new_state = replace(
        state,
        tenant_status=TenantStatus.DELETION_COMMITTING,
        desired_dml_login_state=DmlLoginState.LOCKED,
        request=replace(
            request,
            status=resume_status,
            revision=request.revision + 1,
            execution_generation=generation,
            executor_fencing_token=fencing_token,
            current_action=action,
            failure_resume_status=None,
            failure_code=None,
        ),
    )
    if resume_status is DeletionRequestStatus.COMMITTING:
        effects: Iterable[DeletionEffectKind] = _commit_isolation_effects()
    elif resume_status is DeletionRequestStatus.AWAITING_OFFSITE_ACK:
        effects = (
            DeletionEffectKind.BLOCK_JOB_LEASES,
            DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            DeletionEffectKind.SET_DESIRED_DML_LOCKED,
            DeletionEffectKind.REPLICATE_TOMBSTONE_OFFSITE,
        )
    elif resume_status is DeletionRequestStatus.RELEASING_CLAIMS:
        effects = _claim_release_effects(
            new_state.recovery_dispositions_required
        )
    else:
        effects = _destructive_cleanup_effects()
    tombstone_sequence = (
        new_state.request.tombstone.sequence
        if new_state.request and new_state.request.tombstone
        else None
    )
    return _transition(
        new_state,
        effects=_facts(
            new_state,
            effects,
            tombstone_sequence=tombstone_sequence,
        ),
    )


def _transition(
    state: DeletionState,
    *,
    effects: tuple[DeletionEffectFact, ...] = (),
    idempotent_replay: bool = False,
) -> DeletionTransition:
    return DeletionTransition(
        state=state,
        effects=effects,
        idempotent_replay=idempotent_replay,
    )


def _facts(
    state: DeletionState,
    kinds: Iterable[DeletionEffectKind],
    *,
    tombstone_sequence: Optional[int] = None,
) -> tuple[DeletionEffectFact, ...]:
    request = _require_request(state)
    return tuple(
        DeletionEffectFact(
            kind=kind,
            request_id=request.request_id,
            action_id=request.current_action.action_id,
            execution_generation=request.execution_generation,
            executor_fencing_token=request.executor_fencing_token,
            tenant_access_version=state.tenant_access_version,
            dml_generation=(
                state.candidate_dml_generation
                if kind
                in (
                    DeletionEffectKind.CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE,
                    DeletionEffectKind.LOCK_UNPUBLISHED_DML_CANDIDATE,
                )
                else state.published_dml_generation
                if kind is DeletionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE
                else None
            ),
            tombstone_sequence=tombstone_sequence,
        )
        for kind in kinds
    )


def _commit_isolation_effects() -> tuple[DeletionEffectKind, ...]:
    return (
        DeletionEffectKind.REVOKE_ALL_SESSIONS,
        DeletionEffectKind.DISPOSE_TENANT_ENGINES,
        DeletionEffectKind.BLOCK_JOB_LEASES,
        DeletionEffectKind.RECLAIM_TENANT_JOB_LEASES,
        DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
        DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS,
        DeletionEffectKind.SET_DESIRED_DML_LOCKED,
        DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
        DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS,
    )


def _claim_release_effects(
    recovery_dispositions_required: bool,
) -> tuple[DeletionEffectKind, ...]:
    effects = [
        DeletionEffectKind.RELEASE_TENANT_PROVIDER_CLAIMS,
        DeletionEffectKind.APPEND_PROVIDER_CLAIM_RELEASE_EVENTS,
        DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS,
    ]
    if recovery_dispositions_required:
        effects.append(DeletionEffectKind.RECORD_RECOVERY_TOMBSTONED_DISPOSITIONS)
    return tuple(effects)


def _destructive_cleanup_effects() -> tuple[DeletionEffectKind, ...]:
    return (
        DeletionEffectKind.REVOKE_TENANT_DATABASE_IDENTITIES,
        DeletionEffectKind.REMOVE_TENANT_DATABASE_ROUTES,
        DeletionEffectKind.REMOVE_TENANT_PROVIDER_ACCOUNTS_AND_BINDINGS,
        DeletionEffectKind.DROP_TENANT_SCHEMA,
        DeletionEffectKind.MINIMIZE_TENANT_CONTROL_DATA,
    )


def _action_replay(
    state: DeletionState,
    *,
    action_id: UUID,
    kind: DeletionActionKind,
    idempotency_key: str,
    request_digest: bytes,
) -> bool:
    if state.request is None or state.request.current_action.action_id != action_id:
        return False
    _verify_action_identity(
        state.request.current_action,
        kind=kind,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    return True


def _verify_action_identity(
    action: DeletionAction,
    *,
    kind: DeletionActionKind,
    idempotency_key: str,
    request_digest: bytes,
) -> None:
    if (
        action.kind is not kind
        or action.idempotency_key != idempotency_key
        or action.request_digest != request_digest
    ):
        _fail("DELETION_ACTION_CONFLICT")


def _validate_new_action(action_id: UUID, idempotency_key: str, digest: bytes) -> None:
    _require_uuid("INVALID_DELETION_ACTION_ID", action_id)
    _require_text("INVALID_IDEMPOTENCY_KEY", idempotency_key, maximum=191)
    _require_digest(digest)


def _validate_lockdown_evidence(
    state: DeletionState,
    request: DeletionRequest,
    evidence: DeletionLockdownEvidence,
) -> None:
    _validate_action_evidence(state, request, evidence)


def _validate_action_evidence(
    state: DeletionState,
    request: DeletionRequest,
    evidence: object,
) -> None:
    if getattr(evidence, "action_id", None) != request.current_action.action_id:
        _fail("STALE_DELETION_ACTION_EVIDENCE")
    if getattr(evidence, "execution_generation", None) != request.execution_generation:
        _fail("STALE_DELETION_GENERATION_EVIDENCE")
    if (
        getattr(evidence, "executor_fencing_token", None)
        != request.executor_fencing_token
    ):
        _fail("STALE_DELETION_EXECUTOR_FENCE_EVIDENCE")
    if getattr(evidence, "tenant_access_version", None) != state.tenant_access_version:
        _fail("STALE_TENANT_ACCESS_EVIDENCE")
    if getattr(evidence, "lease_fence_verified", None) is not True:
        _fail("DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED")


def _expect_fences(
    state: DeletionState,
    request: DeletionRequest,
    *,
    expected_request_revision: int,
    expected_access_version: int,
    expected_execution_generation: int,
    expected_executor_fencing_token: int,
) -> None:
    _expect_request_revision(request, expected_request_revision)
    _expect_access(state, expected_access_version)
    if request.execution_generation != expected_execution_generation:
        _fail("STALE_DELETION_EXECUTION_GENERATION")
    if request.executor_fencing_token != expected_executor_fencing_token:
        _fail("STALE_DELETION_EXECUTOR_FENCING_TOKEN")


def _expect_request_revision(request: DeletionRequest, expected: int) -> None:
    if request.revision != expected:
        _fail("STALE_DELETION_REQUEST_REVISION")


def _expect_access(state: DeletionState, expected: int) -> None:
    if state.tenant_access_version != expected:
        _fail("STALE_TENANT_ACCESS_VERSION")


def _require_cooling_window_open(
    request: DeletionRequest,
    database_now_utc: datetime,
) -> None:
    if request.execute_not_before_utc is None:
        _fail("DELETION_APPROVAL_TIME_MISSING")
    if database_now_utc >= request.execute_not_before_utc:
        _fail("DELETION_CANCELLATION_WINDOW_CLOSED")


def _require_request(state: DeletionState) -> DeletionRequest:
    if state.request is None:
        _fail("DELETION_REQUEST_NOT_FOUND")
    return state.request


def _require_uuid(code: str, value: object) -> None:
    if not isinstance(value, UUID):
        _fail(code)


def _require_text(code: str, value: object, *, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _fail(code)


def _require_digest(value: object) -> None:
    if not isinstance(value, bytes) or len(value) != _HASH_BYTES:
        _fail("INVALID_REQUEST_DIGEST")


def _require_hash(code: str, value: object) -> None:
    if not isinstance(value, bytes) or len(value) != _HASH_BYTES:
        _fail(code)


def _require_bool(code: str, value: object) -> None:
    if not isinstance(value, bool):
        _fail(code)


def _require_boolean_fields(value: object, names: Iterable[str]) -> None:
    for name in names:
        _require_bool("INVALID_DELETION_EVIDENCE", getattr(value, name))


def _validate_executor_evidence_fields(value: object) -> None:
    _require_uuid("INVALID_DELETION_ACTION_ID", getattr(value, "action_id", None))
    if getattr(value, "execution_generation", 0) <= 0:
        _fail("INVALID_DELETION_EXECUTION_GENERATION")
    if getattr(value, "executor_fencing_token", 0) <= 0:
        _fail("INVALID_DELETION_EXECUTOR_FENCING_TOKEN")
    if getattr(value, "tenant_access_version", 0) <= 0:
        _fail("INVALID_TENANT_ACCESS_VERSION")
    _require_bool(
        "INVALID_DELETION_LEASE_FENCE_EVIDENCE",
        getattr(value, "lease_fence_verified", None),
    )


def _require_failure_code(value: object) -> None:
    _require_text("INVALID_DELETION_FAILURE_CODE", value, maximum=_MAX_FAILURE_CODE_LENGTH)
    assert isinstance(value, str)
    if (
        value[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        or any(character not in _FAILURE_CODE_ALPHABET for character in value)
    ):
        _fail("INVALID_DELETION_FAILURE_CODE")


def _utc(code: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail(code)
    return value.astimezone(timezone.utc)


def _fail(code: str) -> None:
    raise DeletionTransitionError(code)


__all__ = [
    "DELETION_COOLING_PERIOD",
    "CancellationEvidence",
    "DeletionAction",
    "DeletionActionKind",
    "DeletionActionOutcome",
    "DeletionClaimReleaseEvidence",
    "DeletionEffectFact",
    "DeletionEffectKind",
    "DeletionExecutorFenceEvidence",
    "DeletionIsolationEvidence",
    "DeletionLifecycleContext",
    "DeletionLockdownEvidence",
    "DeletionRequest",
    "DeletionRequestStatus",
    "DeletionReviewDecision",
    "DeletionState",
    "DeletionTombstone",
    "DeletionTransition",
    "DeletionTransitionError",
    "DestructiveCleanupEvidence",
    "OffsiteTombstoneAck",
    "begin_deletion_commit",
    "begin_destructive_cleanup",
    "begin_provider_claim_release",
    "complete_approval_lockdown",
    "complete_deletion",
    "complete_deletion_cancellation",
    "confirm_offsite_tombstone",
    "fail_cooling_action",
    "fail_irreversible_deletion_step",
    "record_permanent_tombstone",
    "request_deletion",
    "request_deletion_cancellation",
    "retry_failed_deletion",
    "review_deletion",
]
