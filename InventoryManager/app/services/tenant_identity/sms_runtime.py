"""Reusable two-transaction SMS delivery boundary for tenant actions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from flask import Request
from sqlalchemy.orm import Session

from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.sms import (
    SmsChallengeContext,
    SmsChallengeService,
    SmsDeliveryOutcome,
    SmsPolicy,
    PreparedSmsDelivery,
    SmsProvider,
    TrustedSourceBucket,
)


SmsContextFactory = Callable[[Session, datetime], SmsChallengeContext]


@dataclass(frozen=True, slots=True)
class SmsChallengeReceipt:
    challenge_id: str
    expires_in_seconds: int
    resend_after_seconds: int


class TenantSmsDeliveryRuntime:
    """Persist, dispatch, and record one challenge without provider-in-DB IO."""

    __slots__ = (
        "_control_database",
        "_root_key_directory",
        "_provider",
        "_policy",
        "_trusted_source_resolver",
        "_challenge_service",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        root_key_directory: str | os.PathLike[str] | None,
        provider: SmsProvider | None,
        policy: SmsPolicy | None,
        trusted_source_resolver,
        challenge_service: SmsChallengeService | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if challenge_service is not None and not isinstance(
            challenge_service, SmsChallengeService
        ):
            raise TypeError("challenge_service must be a SmsChallengeService")
        self._control_database = control_database
        self._root_key_directory = (
            os.fspath(root_key_directory)
            if root_key_directory is not None
            else None
        )
        self._provider = provider
        self._policy = policy
        self._trusted_source_resolver = trusted_source_resolver
        self._challenge_service = challenge_service or SmsChallengeService()

    @property
    def is_configured(self) -> bool:
        return bool(
            self._root_key_directory is not None
            and self._provider is not None
            and self._policy is not None
            and callable(self._trusted_source_resolver)
        )

    @property
    def challenge_service(self) -> SmsChallengeService:
        return self._challenge_service

    @property
    def policy(self) -> SmsPolicy:
        if not isinstance(self._policy, SmsPolicy):
            raise RuntimeError("tenant SMS delivery is not configured")
        return self._policy

    def issue(
        self,
        *,
        flask_request: Request,
        context_factory: SmsContextFactory,
    ) -> SmsChallengeReceipt:
        if not self.is_configured or not callable(context_factory):
            raise RuntimeError("tenant SMS delivery is not configured")
        trusted_source = self._trusted_source_resolver(flask_request)
        if not isinstance(trusted_source, TrustedSourceBucket):
            raise RuntimeError("trusted SMS source is unavailable")

        with self._control_database.transaction() as session:
            database_now = _database_utc_now(session)
            context = context_factory(session, database_now)
            if not isinstance(context, SmsChallengeContext):
                raise TypeError("context_factory must return SmsChallengeContext")
            root_key = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            ).active_key
            prepared = self._challenge_service.prepare_delivery(
                session,
                context=context,
                trusted_source=trusted_source,
                root_key=root_key,
                policy=self.policy,
                now=database_now,
            )

        return self.dispatch_committed(prepared)

    def dispatch_committed(
        self, prepared: PreparedSmsDelivery
    ) -> SmsChallengeReceipt:
        """Dispatch an already committed challenge and persist its outcome."""

        if not self.is_configured or not isinstance(
            prepared, PreparedSmsDelivery
        ):
            raise RuntimeError("tenant SMS delivery is not configured")

        try:
            provider_result = prepared.dispatch_once(self._provider)
            outcome = (
                provider_result
                if isinstance(provider_result, SmsDeliveryOutcome)
                else SmsDeliveryOutcome.SEND_UNKNOWN
            )
        except Exception:
            outcome = SmsDeliveryOutcome.SEND_UNKNOWN

        with self._control_database.transaction() as session:
            self._challenge_service.record_delivery(
                session,
                challenge_id=prepared.challenge_id,
                outcome=outcome,
                now=_database_utc_now(session),
            )
        return SmsChallengeReceipt(
            challenge_id=prepared.challenge_id,
            expires_in_seconds=self.policy.challenge_ttl_seconds,
            resend_after_seconds=self.policy.resend_cooldown_seconds,
        )


def _database_utc_now(session: Session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise RuntimeError("control database time is unavailable")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "SmsChallengeReceipt",
    "TenantSmsDeliveryRuntime",
]
