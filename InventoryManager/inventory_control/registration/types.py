"""Immutable facts for the fenced tenant-registration state machine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


REGISTRATION_LOCK_ORDER = (
    "canonical_user",
    "pending_invitations",
    "provisional_tenant",
    "current_recovery_run",
    "tenant_database_and_route",
    "registration_attempt",
    "replacement_action_and_lineage",
    "redemption_code",
)

_CANONICAL_CN_PHONE = re.compile(r"\+861[0-9]{10}", re.ASCII)
_SAFE_REASON = re.compile(r"[a-z0-9_.:-]{1,64}", re.ASCII)


class RegistrationStatus(str, Enum):
    OTP_VERIFIED = "otp_verified"
    RESERVED = "reserved"
    PROVISIONING = "provisioning"
    READY = "ready"
    COMMITTING = "committing"
    ACTIVE = "active"
    FAILED = "failed"
    IDENTITY_CONFLICT = "identity_conflict"
    SECURITY_BLOCKED = "security_blocked"
    SUPERSEDED_BY_REPLACEMENT = "superseded_by_replacement"
    INTEGRITY_BLOCKED = "integrity_blocked"
    RECOVERY_REVIEW = "recovery_review"


class RegistrationUserStatus(str, Enum):
    UNVERIFIED = "unverified"
    ACTIVE = "active"
    DISABLED = "disabled"


class RegistrationCodeStatus(str, Enum):
    ACTIVE = "active"
    RESERVED = "reserved"
    REDEEMED = "redeemed"
    REVOKED = "revoked"
    RECOVERY_REVOKED = "recovery_revoked"


class RecoveryRunStatus(str, Enum):
    INSTALLING = "installing"
    REVIEWING = "reviewing"
    FAILED_CLOSED = "failed_closed"
    COMPLETED = "completed"


class CommitEvidenceKind(str, Enum):
    ABSENT = "absent"
    COMPLETE = "complete"
    PARTIAL = "partial"
    INCONSISTENT = "inconsistent"


class ProvisionalResourceKind(str, Enum):
    DATABASE = "database"
    SCHEMA = "schema"
    DATABASE_ACCOUNT = "database_account"
    ROUTE = "route"
    JOB = "job"
    PROVIDER_OPERATION = "provider_operation"


class RegistrationOutcome(str, Enum):
    OTP_VERIFIED = "otp_verified"
    CODE_RESERVED = "code_reserved"
    PROVISIONING_STARTED = "provisioning_started"
    DATABASE_READY = "database_ready"
    COMMIT_STARTED = "commit_started"
    ACTIVATED = "activated"
    FAILED_RETAINING_RESERVATION = "failed_retaining_reservation"
    IDENTITY_BLOCKED_RETAINING_RESERVATION = (
        "identity_blocked_retaining_reservation"
    )
    SECURITY_BLOCKED_RETAINING_RESERVATION = (
        "security_blocked_retaining_reservation"
    )
    USER_RETRY_STARTED = "user_retry_started"
    REPLACEMENT_ISSUED = "replacement_issued"
    REPLACEMENT_REPLAY = "replacement_replay"
    COMMITTED_HISTORY_RECONCILED = "committed_history_reconciled"
    INTEGRITY_BLOCKED = "integrity_blocked"
    RECOVERY_REVIEW = "recovery_review"
    IDEMPOTENT_REPLAY = "idempotent_replay"


class RegistrationEffectKind(str, Enum):
    RESERVE_CODE_TO_ATTEMPT = "reserve_code_to_attempt"
    ISSUE_WORKER_LEASE = "issue_worker_lease"
    INVALIDATE_WORKER_LEASE = "invalidate_worker_lease"
    RECORD_DATABASE_PROOF = "record_database_proof"
    PRESERVE_CODE_RESERVATION = "preserve_code_reservation"
    CREATE_REGISTRATION_COMMIT = "create_registration_commit"
    CREATE_FIRST_ADMIN_MEMBERSHIP = "create_first_admin_membership"
    CREATE_SUBSCRIPTION = "create_subscription"
    APPEND_SUBSCRIPTION_EVENT = "append_subscription_event"
    CREATE_RELEASED_HOLD_BASELINE = "create_released_hold_baseline"
    CLAIM_PUBLIC_NAME = "claim_public_name"
    PUBLISH_INITIAL_ROUTE = "publish_initial_route"
    REDEEM_RESERVED_CODE = "redeem_reserved_code"
    SUPERSEDE_PHONE_INVITATIONS = "supersede_phone_invitations"
    RECONCILE_COMPLETE_COMMIT = "reconcile_complete_commit"
    CREATE_INTEGRITY_INCIDENT = "create_integrity_incident"
    REVOKE_SOURCE_CODE_AS_REPLACED = "revoke_source_code_as_replaced"
    CREATE_REPLACEMENT_LINEAGE = "create_replacement_lineage"
    CREATE_SUCCESSOR_CODE = "create_successor_code"
    CREATE_SYSTEM_CLEANUP_OUTBOX = "create_system_cleanup_outbox"
    MARK_CODE_RECOVERY_REVOKED = "mark_code_recovery_revoked"


class RegistrationTransitionError(RuntimeError):
    """Stable fail-closed result with no user-controlled material."""

    def __init__(self, code: str) -> None:
        if _SAFE_REASON.fullmatch(code.lower()) is None:
            raise ValueError("registration error code is invalid")
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ImmutableEntitlementTerms:
    plan_revision_uuid: UUID
    entitlements_schema_version: int
    entitlements_digest: bytes
    exact_duration_seconds: int

    def __post_init__(self) -> None:
        _require_uuid(self.plan_revision_uuid, "plan_revision_uuid")
        _require_positive_int(
            self.entitlements_schema_version, "entitlements_schema_version"
        )
        _require_digest(self.entitlements_digest, "entitlements_digest")
        _require_positive_int(
            self.exact_duration_seconds, "exact_duration_seconds"
        )


@dataclass(frozen=True, slots=True)
class FreshRegisterOtpProof:
    challenge_uuid: UUID
    user_uuid: UUID
    canonical_phone_e164: str
    phone_normalization_version: int
    purpose: str
    verified_at: datetime
    expires_at: datetime
    consumed_once: bool

    def __post_init__(self) -> None:
        _require_uuid(self.challenge_uuid, "challenge_uuid")
        _require_uuid(self.user_uuid, "user_uuid")
        _require_canonical_phone(self.canonical_phone_e164)
        _require_positive_int(
            self.phone_normalization_version, "phone_normalization_version"
        )
        if self.purpose != "register":
            raise ValueError("OTP purpose must be register")
        _require_compatible_datetimes(self.verified_at, self.expires_at)
        if self.expires_at <= self.verified_at:
            raise ValueError("OTP expiry must follow verification")
        if self.consumed_once is not True:
            raise ValueError("OTP proof must be atomically consumed")

    def is_current_at(self, database_now: datetime) -> bool:
        _require_compatible_datetimes(self.verified_at, database_now)
        return self.verified_at <= database_now < self.expires_at


@dataclass(frozen=True, slots=True)
class RevisionFence:
    expected: int
    current: int

    def __post_init__(self) -> None:
        _require_positive_int(self.expected, "expected revision")
        _require_positive_int(self.current, "current revision")

    @property
    def matches(self) -> bool:
        return self.expected == self.current


@dataclass(frozen=True, slots=True)
class CurrentRecoveryRunFacts:
    run_uuid: UUID
    status: RecoveryRunStatus
    revision: RevisionFence
    external_marker_matches: bool

    def __post_init__(self) -> None:
        _require_uuid(self.run_uuid, "run_uuid")
        if not isinstance(self.status, RecoveryRunStatus):
            raise TypeError("status must be a RecoveryRunStatus")
        if not isinstance(self.revision, RevisionFence):
            raise TypeError("revision must be a RevisionFence")
        if not isinstance(self.external_marker_matches, bool):
            raise TypeError("external_marker_matches must be a bool")

    @property
    def permits_registration(self) -> bool:
        return bool(
            self.status is RecoveryRunStatus.COMPLETED
            and self.revision.matches
            and self.external_marker_matches
        )


@dataclass(frozen=True, slots=True)
class WorkerLease:
    lease_uuid: UUID
    owner_uuid: UUID
    execution_generation: int
    fencing_token: int
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.lease_uuid, "lease_uuid")
        _require_uuid(self.owner_uuid, "owner_uuid")
        _require_positive_int(self.execution_generation, "execution_generation")
        _require_positive_int(self.fencing_token, "fencing_token")
        if not isinstance(self.expires_at, datetime):
            raise TypeError("expires_at must be a datetime")


@dataclass(frozen=True, slots=True)
class WorkerFence:
    lease_uuid: UUID
    execution_generation: int
    fencing_token: int

    def __post_init__(self) -> None:
        _require_uuid(self.lease_uuid, "lease_uuid")
        _require_positive_int(self.execution_generation, "execution_generation")
        _require_positive_int(self.fencing_token, "fencing_token")


@dataclass(frozen=True, slots=True)
class CodeFenceFacts:
    code_uuid: UUID
    status: RegistrationCodeStatus
    created_under_recovery_run_uuid: UUID
    revision: RevisionFence
    entitlement_terms: ImmutableEntitlementTerms
    redeem_before: datetime
    reserved_user_uuid: UUID | None = None
    reserved_registration_attempt_uuid: UUID | None = None
    registration_commit_uuid: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.code_uuid, "code_uuid")
        if not isinstance(self.status, RegistrationCodeStatus):
            raise TypeError("status must be a RegistrationCodeStatus")
        _require_uuid(
            self.created_under_recovery_run_uuid,
            "created_under_recovery_run_uuid",
        )
        if not isinstance(self.revision, RevisionFence):
            raise TypeError("revision must be a RevisionFence")
        if not isinstance(self.entitlement_terms, ImmutableEntitlementTerms):
            raise TypeError("entitlement_terms are invalid")
        if not isinstance(self.redeem_before, datetime):
            raise TypeError("redeem_before must be a datetime")
        if self.status is RegistrationCodeStatus.ACTIVE:
            if any(
                value is not None
                for value in (
                    self.reserved_user_uuid,
                    self.reserved_registration_attempt_uuid,
                    self.registration_commit_uuid,
                )
            ):
                raise ValueError("active code cannot have registration bindings")
        elif self.status is RegistrationCodeStatus.RESERVED:
            _require_uuid(self.reserved_user_uuid, "reserved_user_uuid")
            _require_uuid(
                self.reserved_registration_attempt_uuid,
                "reserved_registration_attempt_uuid",
            )
            if self.registration_commit_uuid is not None:
                raise ValueError("reserved code cannot have a commit UUID")
        elif self.status is RegistrationCodeStatus.REDEEMED:
            _require_uuid(self.registration_commit_uuid, "registration_commit_uuid")


@dataclass(frozen=True, slots=True)
class DatabaseProvisioningProof:
    proof_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    database_identity_digest: bytes
    schema_digest: bytes
    schema_generation: int
    execution_generation: int
    worker_lease_uuid: UUID
    worker_fencing_token: int
    smoke_passed: bool
    backup_ddl_lease_held: bool
    database_advisory_lock_held: bool
    business_route_published: bool
    default_warehouse_created: bool
    contact_phone_prefilled_unconfirmed: bool

    def __post_init__(self) -> None:
        for field, name in (
            (self.proof_uuid, "proof_uuid"),
            (self.tenant_uuid, "tenant_uuid"),
            (self.database_uuid, "database_uuid"),
            (self.worker_lease_uuid, "worker_lease_uuid"),
        ):
            _require_uuid(field, name)
        _require_digest(
            self.database_identity_digest, "database_identity_digest"
        )
        _require_digest(self.schema_digest, "schema_digest")
        _require_positive_int(self.schema_generation, "schema_generation")
        _require_positive_int(self.execution_generation, "execution_generation")
        _require_positive_int(self.worker_fencing_token, "worker_fencing_token")
        for value, name in (
            (self.smoke_passed, "smoke_passed"),
            (self.backup_ddl_lease_held, "backup_ddl_lease_held"),
            (
                self.database_advisory_lock_held,
                "database_advisory_lock_held",
            ),
            (self.business_route_published, "business_route_published"),
            (self.default_warehouse_created, "default_warehouse_created"),
            (
                self.contact_phone_prefilled_unconfirmed,
                "contact_phone_prefilled_unconfirmed",
            ),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool")


@dataclass(frozen=True, slots=True)
class RegistrationCommitEvidence:
    kind: CommitEvidenceKind
    registration_commit_uuid: UUID | None = None
    anchors_match_immutable_source: bool = False
    safe_incident_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CommitEvidenceKind):
            raise TypeError("kind must be a CommitEvidenceKind")
        if self.kind is CommitEvidenceKind.ABSENT:
            if self.registration_commit_uuid is not None:
                raise ValueError("absent commit evidence cannot name a commit")
        elif self.kind is CommitEvidenceKind.COMPLETE:
            _require_uuid(
                self.registration_commit_uuid, "registration_commit_uuid"
            )
            if self.anchors_match_immutable_source is not True:
                raise ValueError("complete commit anchors must match")
        else:
            if (
                not isinstance(self.safe_incident_reason, str)
                or _SAFE_REASON.fullmatch(self.safe_incident_reason) is None
            ):
                raise ValueError("blocked commit evidence needs a safe reason")


@dataclass(frozen=True, slots=True)
class RegistrationPublishPlan:
    registration_commit_uuid: UUID
    admin_membership_uuid: UUID
    subscription_uuid: UUID
    subscription_event_uuid: UUID
    route_anchor_uuid: UUID
    public_name_claim_uuid: UUID
    released_hold_uuid: UUID

    def __post_init__(self) -> None:
        values = (
            self.registration_commit_uuid,
            self.admin_membership_uuid,
            self.subscription_uuid,
            self.subscription_event_uuid,
            self.route_anchor_uuid,
            self.public_name_claim_uuid,
            self.released_hold_uuid,
        )
        for value in values:
            _require_uuid(value, "publish anchor UUID")
        if len(set(values)) != len(values):
            raise ValueError("publish anchor UUIDs must be distinct")


@dataclass(frozen=True, slots=True)
class ObservedRegistrationAnchors:
    publish_plan: RegistrationPublishPlan
    code_uuid: UUID
    user_uuid: UUID
    attempt_uuid: UUID
    tenant_uuid: UUID
    entitlement_terms: ImmutableEntitlementTerms
    atomic_control_transaction: bool
    code_redeemed_to_commit: bool
    first_admin_created: bool
    subscription_and_event_created: bool
    route_and_name_published: bool
    released_hold_created: bool
    pending_invitations_superseded: bool
    no_route_was_published_early: bool

    def __post_init__(self) -> None:
        if not isinstance(self.publish_plan, RegistrationPublishPlan):
            raise TypeError("publish_plan is invalid")
        for value, name in (
            (self.code_uuid, "code_uuid"),
            (self.user_uuid, "user_uuid"),
            (self.attempt_uuid, "attempt_uuid"),
            (self.tenant_uuid, "tenant_uuid"),
        ):
            _require_uuid(value, name)
        if not isinstance(self.entitlement_terms, ImmutableEntitlementTerms):
            raise TypeError("entitlement_terms are invalid")
        for value in (
            self.atomic_control_transaction,
            self.code_redeemed_to_commit,
            self.first_admin_created,
            self.subscription_and_event_created,
            self.route_and_name_published,
            self.released_hold_created,
            self.pending_invitations_superseded,
            self.no_route_was_published_early,
        ):
            if not isinstance(value, bool):
                raise TypeError("anchor completion flags must be bools")

    @property
    def is_complete(self) -> bool:
        return all(
            (
                self.atomic_control_transaction,
                self.code_redeemed_to_commit,
                self.first_admin_created,
                self.subscription_and_event_created,
                self.route_and_name_published,
                self.released_hold_created,
                self.pending_invitations_superseded,
                self.no_route_was_published_early,
            )
        )


@dataclass(frozen=True, slots=True)
class ProvisionalResourceFacts:
    resources: frozenset[ProvisionalResourceKind]
    observed_generation: int
    observed_active_lease_uuid: UUID | None
    backup_ddl_lease_held: bool
    database_advisory_lock_held: bool

    def __post_init__(self) -> None:
        if not isinstance(self.resources, frozenset) or not all(
            isinstance(value, ProvisionalResourceKind) for value in self.resources
        ):
            raise TypeError("resources must be a frozen set of resource kinds")
        _require_positive_int(self.observed_generation, "observed_generation")
        if self.observed_active_lease_uuid is not None:
            _require_uuid(
                self.observed_active_lease_uuid,
                "observed_active_lease_uuid",
            )
        for value, name in (
            (self.backup_ddl_lease_held, "backup_ddl_lease_held"),
            (
                self.database_advisory_lock_held,
                "database_advisory_lock_held",
            ),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool")
        if self.has_database_scoped_resource:
            if not (
                self.backup_ddl_lease_held
                and self.database_advisory_lock_held
            ):
                raise ValueError(
                    "database resources require backup/DDL and advisory locks"
                )
        elif self.backup_ddl_lease_held or self.database_advisory_lock_held:
            raise ValueError("resource-free replacement cannot claim database locks")

    @property
    def has_any(self) -> bool:
        return bool(self.resources)

    @property
    def has_database_scoped_resource(self) -> bool:
        return bool(
            self.resources
            & {
                ProvisionalResourceKind.DATABASE,
                ProvisionalResourceKind.SCHEMA,
                ProvisionalResourceKind.DATABASE_ACCOUNT,
                ProvisionalResourceKind.ROUTE,
            }
        )


@dataclass(frozen=True, slots=True)
class ReplacementPlan:
    replacement_action_uuid: UUID
    successor_code_uuid: UUID
    successor_batch_uuid: UUID
    successor_crypto_context_uuid: UUID
    new_redeem_before: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        values = (
            self.replacement_action_uuid,
            self.successor_code_uuid,
            self.successor_batch_uuid,
            self.successor_crypto_context_uuid,
        )
        for value in values:
            _require_uuid(value, "replacement UUID")
        if len(set(values)) != len(values):
            raise ValueError("replacement UUIDs must be distinct")
        if not isinstance(self.new_redeem_before, datetime):
            raise TypeError("new_redeem_before must be a datetime")
        if (
            not isinstance(self.idempotency_key, str)
            or not 1 <= len(self.idempotency_key) <= 128
        ):
            raise ValueError("idempotency_key is invalid")


@dataclass(frozen=True, slots=True)
class ReplacementLineage:
    source_code_uuid: UUID
    source_attempt_uuid: UUID
    replacement_action_uuid: UUID
    successor_code_uuid: UUID
    successor_batch_uuid: UUID
    successor_crypto_context_uuid: UUID
    created_under_recovery_run_uuid: UUID
    new_redeem_before: datetime
    idempotency_key: str
    copied_entitlement_terms: ImmutableEntitlementTerms

    def __post_init__(self) -> None:
        values = (
            self.source_code_uuid,
            self.source_attempt_uuid,
            self.replacement_action_uuid,
            self.successor_code_uuid,
            self.successor_batch_uuid,
            self.successor_crypto_context_uuid,
            self.created_under_recovery_run_uuid,
        )
        for value in values:
            _require_uuid(value, "replacement lineage UUID")
        if not isinstance(self.new_redeem_before, datetime):
            raise TypeError("new_redeem_before must be a datetime")
        if (
            not isinstance(self.idempotency_key, str)
            or not 1 <= len(self.idempotency_key) <= 128
        ):
            raise ValueError("idempotency_key is invalid")
        if not isinstance(
            self.copied_entitlement_terms, ImmutableEntitlementTerms
        ):
            raise TypeError("copied entitlement terms are invalid")


@dataclass(frozen=True, slots=True)
class RegistrationAttemptState:
    attempt_uuid: UUID
    user_uuid: UUID
    canonical_phone_e164: str
    phone_normalization_version: int
    tenant_uuid: UUID
    database_uuid: UUID
    code_uuid: UUID
    requested_name_digest: bytes
    entitlement_terms: ImmutableEntitlementTerms
    created_under_recovery_run_uuid: UUID
    status: RegistrationStatus
    provisioning_generation: int
    state_revision: int
    last_register_otp_challenge_uuid: UUID
    active_lease: WorkerLease | None = None
    database_proof: DatabaseProvisioningProof | None = None
    commit_plan: RegistrationPublishPlan | None = None
    registration_commit_uuid: UUID | None = None
    replacement_lineage: ReplacementLineage | None = None
    integrity_reason_code: str | None = None
    recovery_review_run_uuid: UUID | None = None
    status_before_recovery_review: RegistrationStatus | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.attempt_uuid, "attempt_uuid"),
            (self.user_uuid, "user_uuid"),
            (self.tenant_uuid, "tenant_uuid"),
            (self.database_uuid, "database_uuid"),
            (self.code_uuid, "code_uuid"),
            (
                self.created_under_recovery_run_uuid,
                "created_under_recovery_run_uuid",
            ),
            (
                self.last_register_otp_challenge_uuid,
                "last_register_otp_challenge_uuid",
            ),
        ):
            _require_uuid(value, name)
        _require_canonical_phone(self.canonical_phone_e164)
        _require_positive_int(
            self.phone_normalization_version, "phone_normalization_version"
        )
        _require_digest(self.requested_name_digest, "requested_name_digest")
        if not isinstance(self.entitlement_terms, ImmutableEntitlementTerms):
            raise TypeError("entitlement_terms are invalid")
        if not isinstance(self.status, RegistrationStatus):
            raise TypeError("status must be a RegistrationStatus")
        _require_positive_int(
            self.provisioning_generation, "provisioning_generation"
        )
        _require_positive_int(self.state_revision, "state_revision")
        leased_states = {
            RegistrationStatus.PROVISIONING,
            RegistrationStatus.READY,
            RegistrationStatus.COMMITTING,
        }
        if (self.status in leased_states) != (self.active_lease is not None):
            raise ValueError("worker lease does not match registration status")
        if self.active_lease is not None and (
            self.active_lease.execution_generation
            != self.provisioning_generation
        ):
            raise ValueError("worker lease generation is stale")
        if self.status in {RegistrationStatus.READY, RegistrationStatus.COMMITTING}:
            if self.database_proof is None:
                raise ValueError("ready registration requires database proof")
        if self.status is RegistrationStatus.COMMITTING:
            if self.commit_plan is None:
                raise ValueError("committing registration requires publish plan")
        elif (
            self.status is not RegistrationStatus.ACTIVE
            and self.commit_plan is not None
        ):
            raise ValueError("publish plan is not valid for this status")
        if self.status is RegistrationStatus.ACTIVE:
            _require_uuid(
                self.registration_commit_uuid, "registration_commit_uuid"
            )
            if self.commit_plan is None:
                raise ValueError("active registration requires publish plan")
            if (
                self.commit_plan.registration_commit_uuid
                != self.registration_commit_uuid
            ):
                raise ValueError("active commit UUID does not match publish plan")
        elif self.registration_commit_uuid is not None:
            raise ValueError("only active registration may hold a commit UUID")
        if self.status is RegistrationStatus.SUPERSEDED_BY_REPLACEMENT:
            if self.replacement_lineage is None:
                raise ValueError("superseded registration requires lineage")
            if (
                self.replacement_lineage.source_code_uuid != self.code_uuid
                or self.replacement_lineage.source_attempt_uuid
                != self.attempt_uuid
                or self.replacement_lineage.copied_entitlement_terms
                != self.entitlement_terms
            ):
                raise ValueError("replacement lineage does not match source")
        elif self.replacement_lineage is not None:
            raise ValueError("replacement lineage is terminal")
        if self.status is RegistrationStatus.INTEGRITY_BLOCKED:
            if (
                not isinstance(self.integrity_reason_code, str)
                or _SAFE_REASON.fullmatch(self.integrity_reason_code) is None
            ):
                raise ValueError("integrity block requires a safe reason")
        elif self.integrity_reason_code is not None:
            raise ValueError("integrity reason is not valid for this status")
        if self.status is RegistrationStatus.RECOVERY_REVIEW:
            _require_uuid(
                self.recovery_review_run_uuid, "recovery_review_run_uuid"
            )
            if not isinstance(
                self.status_before_recovery_review, RegistrationStatus
            ):
                raise ValueError("recovery review requires prior status")
        elif (
            self.recovery_review_run_uuid is not None
            or self.status_before_recovery_review is not None
        ):
            raise ValueError("recovery review facts are not valid for this status")


@dataclass(frozen=True, slots=True)
class RegistrationEffectFacts:
    previous_generation: int
    current_generation: int
    preserve_code_binding: bool
    invalidated_lease_uuid: UUID | None = None
    issued_lease: WorkerLease | None = None
    database_proof: DatabaseProvisioningProof | None = None
    publish_plan: RegistrationPublishPlan | None = None
    replacement_lineage: ReplacementLineage | None = None
    cleanup_outbox_required: bool = False
    integrity_incident_reason: str | None = None

    def __post_init__(self) -> None:
        _require_positive_int(self.previous_generation, "previous_generation")
        _require_positive_int(self.current_generation, "current_generation")
        if self.current_generation < self.previous_generation:
            raise ValueError("registration generation cannot decrease")
        if not isinstance(self.preserve_code_binding, bool):
            raise TypeError("preserve_code_binding must be a bool")
        if not isinstance(self.cleanup_outbox_required, bool):
            raise TypeError("cleanup_outbox_required must be a bool")


@dataclass(frozen=True, slots=True)
class RegistrationCompletionConditions:
    required_lock_order: tuple[str, ...]
    require_atomic_control_transaction: bool
    no_publish_before_all_fences: bool
    code_binding_must_match: bool
    completion_predicates: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.required_lock_order, tuple):
            raise TypeError("required_lock_order must be a tuple")
        if not isinstance(self.completion_predicates, tuple):
            raise TypeError("completion_predicates must be a tuple")


@dataclass(frozen=True, slots=True)
class RegistrationTransition:
    before: RegistrationAttemptState | None
    after: RegistrationAttemptState
    outcome: RegistrationOutcome
    effects: tuple[RegistrationEffectKind, ...]
    effect_facts: RegistrationEffectFacts
    completion: RegistrationCompletionConditions


def _require_uuid(value: object, field: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field} must be a UUID")


def _require_positive_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")


def _require_digest(value: object, field: str) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{field} must contain a 32-byte digest")


def _require_canonical_phone(value: object) -> None:
    if not isinstance(value, str) or _CANONICAL_CN_PHONE.fullmatch(value) is None:
        raise ValueError("canonical_phone_e164 is invalid")


def _require_compatible_datetimes(first: datetime, second: datetime) -> None:
    if not isinstance(first, datetime) or not isinstance(second, datetime):
        raise TypeError("registration times must be datetimes")
    if first.tzinfo != second.tzinfo:
        raise ValueError("registration times must use one timezone form")
