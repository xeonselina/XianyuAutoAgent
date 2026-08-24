"""Caller-transactional issuance, delivery, quota, and consumption service."""

from __future__ import annotations

import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from inventory_control.crypto.root_key import RootKey
from inventory_control.models.sms import SmsChallenge, SmsRateLimitSubject

from .contracts import (
    CanonicalSmsPhone,
    PreparedSmsDelivery,
    SmsChallengeContext,
    SmsDeliveryOutcome,
    SmsPolicy,
    SmsPurpose,
    SmsVerificationResult,
    TrustedSourceBucket,
)
from .crypto import (
    SMS_HMAC_PROTOCOL_VERSION,
    calculate_code_hmac,
    verify_code_hmac,
)


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_COUNTED_DELIVERY_STATES = ("committed", "sent", "send_unknown")
_VERIFIABLE_DELIVERY_STATES = ("sent", "send_unknown")
_PUBLIC_REJECTION = SmsVerificationResult(
    accepted=False, reason_code="SMS_CHALLENGE_REJECTED"
)
_PUBLIC_ACCEPTANCE = SmsVerificationResult(
    accepted=True, reason_code="SMS_CHALLENGE_CONSUMED"
)


class SmsSendRejected(RuntimeError):
    """A stable, non-enumerating send rejection with bounded retry advice."""

    code = "SMS_SEND_REJECTED"

    def __init__(self, *, reason_code: str, retry_after_seconds: int) -> None:
        super().__init__("SMS verification is temporarily unavailable.")
        self.reason_code = reason_code
        self.retry_after_seconds = max(1, retry_after_seconds)


class SmsDeliveryStateError(RuntimeError):
    code = "SMS_DELIVERY_STATE_INVALID"

    def __init__(self) -> None:
        super().__init__("SMS delivery state cannot be changed.")


class SmsChallengeService:
    """Operate SMS rows without committing or invoking a real provider.

    The caller owns every database transaction.  ``prepare_delivery`` writes a
    ``committed`` reservation and returns a one-shot in-memory adapter bridge;
    callers must commit that transaction before invoking ``dispatch_once``.
    Delivery evidence is then recorded in a separate caller-owned transaction.
    Successful verification remains in the same transaction as the protected
    login or action, making consumption and the downstream mutation atomic.
    """

    def __init__(
        self,
        *,
        code_generator: Callable[[], str] | None = None,
    ) -> None:
        self._code_generator = code_generator or _generate_six_digit_code

    def prepare_delivery(
        self,
        session: Session,
        *,
        context: SmsChallengeContext,
        trusted_source: TrustedSourceBucket,
        root_key: RootKey,
        policy: SmsPolicy,
        now: datetime | None = None,
    ) -> PreparedSmsDelivery:
        """Reserve quota and persist a plaintext-free committed challenge."""

        _require_inputs(context, trusted_source, root_key, policy)
        current_time = _as_utc(now or _utc_now())
        self._lock_rate_limit_subjects(
            session,
            phone=context.phone,
            trusted_source=trusted_source,
            now=current_time,
        )
        self._enforce_no_inflight_delivery(
            session, phone=context.phone, policy=policy, now=current_time
        )
        self._enforce_cooldown(
            session, phone=context.phone, policy=policy, now=current_time
        )
        self._enforce_rate_limits(
            session,
            phone=context.phone,
            trusted_source=trusted_source,
            policy=policy,
            now=current_time,
        )

        plaintext_code = self._code_generator()
        if not _is_six_ascii_digits(plaintext_code):
            raise RuntimeError("SMS code generator returned an invalid value")
        challenge_id = str(uuid4())
        code_hmac = calculate_code_hmac(
            root_key=root_key,
            challenge_id=challenge_id,
            context=context,
            plaintext_code=plaintext_code,
        )
        row = SmsChallenge(
            id=challenge_id,
            purpose=context.purpose.value,
            canonical_phone_e164=context.phone.e164,
            phone_normalization_version=context.phone.normalization_version,
            phone_metadata_version=context.phone.metadata_version,
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            actor_session_id=context.actor_session_id,
            action_payload_digest_sha256=context.action_payload.digest_sha256,
            authoritative_revision=context.authoritative_revision,
            code_hmac_sha256=code_hmac,
            root_key_version=root_key.version,
            hmac_protocol_version=SMS_HMAC_PROTOCOL_VERSION,
            policy_version=policy.version,
            max_wrong_attempts=policy.max_wrong_attempts,
            trusted_source_bucket=trusted_source.value,
            delivery_state="committed",
            verification_state="pending_delivery",
            wrong_attempt_count=0,
            row_version=1,
            created_at=current_time,
            expires_at=current_time + timedelta(seconds=policy.challenge_ttl_seconds),
        )
        session.add(row)
        session.flush()
        return PreparedSmsDelivery(
            challenge_id=challenge_id,
            canonical_phone_e164=context.phone.e164,
            purpose=context.purpose,
            plaintext_code=plaintext_code,
        )

    def record_delivery(
        self,
        session: Session,
        *,
        challenge_id: str,
        outcome: SmsDeliveryOutcome,
        now: datetime | None = None,
    ) -> bool:
        """Record one provider result; identical repeats are idempotent."""

        try:
            selected_outcome = SmsDeliveryOutcome(outcome)
        except (TypeError, ValueError):
            raise SmsDeliveryStateError() from None
        current_time = _as_utc(now or _utc_now())
        summary = session.execute(
            sa.select(
                SmsChallenge.canonical_phone_e164,
                SmsChallenge.phone_normalization_version,
                SmsChallenge.phone_metadata_version,
                SmsChallenge.trusted_source_bucket,
            ).where(SmsChallenge.id == challenge_id)
        ).one_or_none()
        if summary is None:
            raise SmsDeliveryStateError()
        phone = CanonicalSmsPhone(
            e164=summary.canonical_phone_e164,
            normalization_version=summary.phone_normalization_version,
            metadata_version=summary.phone_metadata_version,
        )
        trusted_source = _trusted_source_from_stored(summary.trusted_source_bucket)
        self._lock_rate_limit_subjects(
            session,
            phone=phone,
            trusted_source=trusted_source,
            now=current_time,
        )

        challenge = session.scalar(
            sa.select(SmsChallenge)
            .where(SmsChallenge.id == challenge_id)
            .with_for_update()
        )
        if challenge is None:
            raise SmsDeliveryStateError()
        if challenge.delivery_state == selected_outcome.value:
            return False
        if challenge.delivery_state != "committed":
            raise SmsDeliveryStateError()

        peers = list(
            session.scalars(
                sa.select(SmsChallenge)
                .where(
                    SmsChallenge.canonical_phone_e164 == challenge.canonical_phone_e164,
                    SmsChallenge.purpose == challenge.purpose,
                )
                .order_by(SmsChallenge.created_at, SmsChallenge.id)
                .with_for_update()
            )
        )
        challenge.delivery_state = selected_outcome.value
        challenge.delivery_recorded_at = current_time
        challenge.row_version += 1

        if selected_outcome is SmsDeliveryOutcome.FAILED:
            _invalidate_if_open(challenge, now=current_time, reason="delivery_failed")
        else:
            if challenge.verification_state == "pending_delivery":
                if current_time >= _as_utc(challenge.expires_at):
                    _invalidate_if_open(
                        challenge, now=current_time, reason="expired_before_delivery"
                    )
                else:
                    challenge.verification_state = "active"
            challenge_order = _challenge_order(challenge)
            newer_delivered = any(
                peer.id != challenge.id
                and peer.delivery_state in _VERIFIABLE_DELIVERY_STATES
                and _challenge_order(peer) > challenge_order
                for peer in peers
            )
            if newer_delivered:
                _invalidate_if_open(
                    challenge, now=current_time, reason="superseded_by_newer_challenge"
                )
            else:
                for peer in peers:
                    if (
                        peer.id != challenge.id
                        and _challenge_order(peer) < challenge_order
                    ):
                        _invalidate_if_open(
                            peer,
                            now=current_time,
                            reason="superseded_by_newer_challenge",
                        )
        session.flush()
        return True

    def verify_and_consume(
        self,
        session: Session,
        *,
        challenge_id: str,
        context: SmsChallengeContext,
        plaintext_code: object,
        root_key: RootKey,
        now: datetime | None = None,
    ) -> SmsVerificationResult:
        """Consume once or return one fixed rejection suitable for committing."""

        if not isinstance(context, SmsChallengeContext) or not isinstance(
            root_key, RootKey
        ):
            return _PUBLIC_REJECTION
        current_time = _as_utc(now or _utc_now())
        challenge = session.scalar(
            sa.select(SmsChallenge)
            .where(SmsChallenge.id == challenge_id)
            .with_for_update()
        )
        if challenge is None or not _context_matches(challenge, context):
            return _PUBLIC_REJECTION
        if (
            challenge.root_key_version != root_key.version
            or challenge.delivery_state not in _VERIFIABLE_DELIVERY_STATES
            or challenge.verification_state != "active"
            or current_time >= _as_utc(challenge.expires_at)
        ):
            return _PUBLIC_REJECTION

        code_is_valid = _is_six_ascii_digits(plaintext_code)
        candidate_code = plaintext_code if code_is_valid else "000000"
        matches = verify_code_hmac(
            root_key=root_key,
            challenge_id=challenge.id,
            context=context,
            plaintext_code=candidate_code,
            expected_hmac=bytes(challenge.code_hmac_sha256),
            protocol_version=challenge.hmac_protocol_version,
        )
        if matches and code_is_valid:
            changed = session.execute(
                sa.update(SmsChallenge)
                .where(
                    SmsChallenge.id == challenge.id,
                    SmsChallenge.row_version == challenge.row_version,
                    SmsChallenge.verification_state == "active",
                    SmsChallenge.consumed_at.is_(None),
                    SmsChallenge.expires_at > current_time,
                )
                .values(
                    verification_state="consumed",
                    consumed_at=current_time,
                    row_version=challenge.row_version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount == 1:
                session.expire(challenge)
                return _PUBLIC_ACCEPTANCE
            return _PUBLIC_REJECTION

        next_attempt = challenge.wrong_attempt_count + 1
        locks_challenge = next_attempt >= challenge.max_wrong_attempts
        values: dict[str, object] = {
            "wrong_attempt_count": next_attempt,
            "row_version": challenge.row_version + 1,
        }
        if locks_challenge:
            values.update(
                verification_state="locked",
                locked_at=current_time,
            )
        changed = session.execute(
            sa.update(SmsChallenge)
            .where(
                SmsChallenge.id == challenge.id,
                SmsChallenge.row_version == challenge.row_version,
                SmsChallenge.verification_state == "active",
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount == 1:
            session.expire(challenge)
        return _PUBLIC_REJECTION

    def _lock_rate_limit_subjects(
        self,
        session: Session,
        *,
        phone: CanonicalSmsPhone,
        trusted_source: TrustedSourceBucket,
        now: datetime,
    ) -> None:
        subjects = sorted((("phone", phone.e164), ("source", trusted_source.value)))
        dialect_name = session.get_bind().dialect.name
        for subject_type, subject_bucket in subjects:
            values = {
                "subject_type": subject_type,
                "subject_bucket": subject_bucket,
                "row_version": 1,
                "created_at": now,
                "updated_at": now,
            }
            if dialect_name in {"mysql", "mariadb"}:
                statement = mysql.insert(SmsRateLimitSubject).values(**values)
                session.execute(
                    statement.on_duplicate_key_update(
                        subject_bucket=statement.inserted.subject_bucket
                    )
                )
            else:
                raise RuntimeError("SMS rate limiting requires MySQL or MariaDB")

        for subject_type, subject_bucket in subjects:
            locked = session.scalar(
                sa.select(SmsRateLimitSubject)
                .where(
                    SmsRateLimitSubject.subject_type == subject_type,
                    SmsRateLimitSubject.subject_bucket == subject_bucket,
                )
                .with_for_update()
            )
            if locked is None:
                raise RuntimeError("SMS rate-limit subject could not be locked")

    def _enforce_no_inflight_delivery(
        self,
        session: Session,
        *,
        phone: CanonicalSmsPhone,
        policy: SmsPolicy,
        now: datetime,
    ) -> None:
        inflight = session.scalar(
            sa.select(SmsChallenge)
            .where(
                SmsChallenge.canonical_phone_e164 == phone.e164,
                SmsChallenge.delivery_state == "committed",
                SmsChallenge.created_at
                > now - timedelta(seconds=policy.challenge_ttl_seconds),
            )
            .order_by(SmsChallenge.created_at.desc(), SmsChallenge.id.desc())
            .limit(1)
            .with_for_update()
        )
        if inflight is not None:
            retry_at = _as_utc(inflight.created_at) + timedelta(
                seconds=policy.challenge_ttl_seconds
            )
            raise SmsSendRejected(
                reason_code="SMS_SEND_IN_PROGRESS",
                retry_after_seconds=_retry_seconds(retry_at, now),
            )

    def _enforce_cooldown(
        self,
        session: Session,
        *,
        phone: CanonicalSmsPhone,
        policy: SmsPolicy,
        now: datetime,
    ) -> None:
        previous = session.scalar(
            sa.select(SmsChallenge)
            .where(
                SmsChallenge.canonical_phone_e164 == phone.e164,
                SmsChallenge.delivery_state.in_(_VERIFIABLE_DELIVERY_STATES),
                SmsChallenge.delivery_recorded_at.is_not(None),
            )
            .order_by(SmsChallenge.delivery_recorded_at.desc(), SmsChallenge.id.desc())
            .limit(1)
            .with_for_update()
        )
        if previous is None:
            return
        retry_at = _as_utc(previous.delivery_recorded_at) + timedelta(
            seconds=policy.resend_cooldown_seconds
        )
        if retry_at > now:
            raise SmsSendRejected(
                reason_code="SMS_RESEND_COOLDOWN",
                retry_after_seconds=_retry_seconds(retry_at, now),
            )

    def _enforce_rate_limits(
        self,
        session: Session,
        *,
        phone: CanonicalSmsPhone,
        trusted_source: TrustedSourceBucket,
        policy: SmsPolicy,
        now: datetime,
    ) -> None:
        hour_start = now - timedelta(hours=1)
        day_start, next_day = _shanghai_day_bounds(now)
        checks = (
            (
                SmsChallenge.canonical_phone_e164 == phone.e164,
                hour_start,
                now,
                policy.phone_rolling_hour_limit,
                "SMS_PHONE_HOURLY_LIMIT",
                None,
            ),
            (
                SmsChallenge.canonical_phone_e164 == phone.e164,
                day_start,
                now,
                policy.phone_shanghai_day_limit,
                "SMS_PHONE_DAILY_LIMIT",
                next_day,
            ),
            (
                SmsChallenge.trusted_source_bucket == trusted_source.value,
                hour_start,
                now,
                policy.source_rolling_hour_limit,
                "SMS_SOURCE_HOURLY_LIMIT",
                None,
            ),
            (
                SmsChallenge.trusted_source_bucket == trusted_source.value,
                day_start,
                now,
                policy.source_shanghai_day_limit,
                "SMS_SOURCE_DAILY_LIMIT",
                next_day,
            ),
        )
        for (
            predicate,
            window_start,
            window_end,
            limit,
            reason,
            fixed_retry_at,
        ) in checks:
            events = list(
                session.scalars(
                    sa.select(SmsChallenge.created_at)
                    .where(
                        predicate,
                        SmsChallenge.delivery_state.in_(_COUNTED_DELIVERY_STATES),
                        SmsChallenge.created_at >= window_start,
                        SmsChallenge.created_at <= window_end,
                    )
                    .order_by(SmsChallenge.created_at, SmsChallenge.id)
                    .with_for_update()
                )
            )
            if len(events) < limit:
                continue
            retry_at = fixed_retry_at or (_as_utc(events[0]) + timedelta(hours=1))
            raise SmsSendRejected(
                reason_code=reason,
                retry_after_seconds=_retry_seconds(retry_at, now),
            )


def _require_inputs(
    context: SmsChallengeContext,
    trusted_source: TrustedSourceBucket,
    root_key: RootKey,
    policy: SmsPolicy,
) -> None:
    if not isinstance(context, SmsChallengeContext):
        raise TypeError("context must be an SmsChallengeContext")
    if not isinstance(trusted_source, TrustedSourceBucket):
        raise TypeError("trusted_source must come from the trusted request boundary")
    if not isinstance(root_key, RootKey):
        raise TypeError("root_key must be a RootKey")
    if not isinstance(policy, SmsPolicy):
        raise TypeError("policy must be an SmsPolicy")


def _context_matches(row: SmsChallenge, context: SmsChallengeContext) -> bool:
    return bool(
        row.purpose == context.purpose.value
        and row.canonical_phone_e164 == context.phone.e164
        and row.phone_normalization_version == context.phone.normalization_version
        and row.phone_metadata_version == context.phone.metadata_version
        and row.user_id == context.user_id
        and row.tenant_id == context.tenant_id
        and row.actor_session_id == context.actor_session_id
        and row.authoritative_revision == context.authoritative_revision
        and hmac.compare_digest(
            bytes(row.action_payload_digest_sha256),
            context.action_payload.digest_sha256,
        )
    )


def _invalidate_if_open(challenge: SmsChallenge, *, now: datetime, reason: str) -> None:
    if challenge.verification_state not in {"pending_delivery", "active"}:
        return
    challenge.verification_state = "invalidated"
    challenge.invalidated_at = now
    challenge.invalidated_reason_code = reason
    challenge.row_version += 1


def _trusted_source_from_stored(value: str) -> TrustedSourceBucket:
    if value == "unknown":
        return TrustedSourceBucket.unknown()
    prefix, _, address = value.partition(":")
    if prefix not in {"ip4", "ip6"}:
        raise SmsDeliveryStateError()
    return TrustedSourceBucket.from_trusted_ip(address)


def _challenge_order(challenge: SmsChallenge) -> tuple[datetime, str]:
    return (_as_utc(challenge.created_at), challenge.id)


def _generate_six_digit_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _is_six_ascii_digits(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 6
        and value.isascii()
        and value.isdigit()
    )


def _shanghai_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local_now = now.astimezone(_SHANGHAI)
    day_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day_local = day_start_local + timedelta(days=1)
    return (
        day_start_local.astimezone(timezone.utc),
        next_day_local.astimezone(timezone.utc),
    )


def _retry_seconds(retry_at: datetime, now: datetime) -> int:
    return max(1, math.ceil((retry_at - now).total_seconds()))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
