"""One-shot exact-revision credential bridge for Xianyu synchronization.

This module performs no provider I/O and never owns the control transaction.
It freezes the current authority named by a durable job, authenticates exactly
that encrypted revision, and returns a redacted request for immediate use by
an outer provider adapter after the transaction has closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.crypto import RootKeyLoadError, RootKeyRing
from inventory_control.models import (
    TenantIntegration,
    TenantIntegrationSecretRevision,
)

from .errors import (
    IntegrationCredentialAuthenticationError,
    IntegrationCredentialUnavailableError,
)
from .service import TenantIntegrationService


class XianyuSyncCredentialError(RuntimeError):
    code = "XIANYU_SYNC_CREDENTIAL_UNAVAILABLE"
    public_message = "Xianyu synchronization credentials are unavailable"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class XianyuSyncCredentialInputError(XianyuSyncCredentialError):
    code = "XIANYU_SYNC_CREDENTIAL_INPUT_INVALID"
    public_message = "Xianyu synchronization credential request is invalid"


@dataclass(frozen=True, slots=True)
class XianyuSyncExecutionContext:
    tenant_uuid: str
    integration_uuid: str
    secret_revision_uuid: str
    integration_row_version: int
    revision_row_version: int

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_uuid",
            "integration_uuid",
            "secret_revision_uuid",
        ):
            object.__setattr__(self, field_name, _uuid(getattr(self, field_name)))
        _positive(self.integration_row_version)
        _positive(self.revision_row_version)


class XianyuSyncProviderRequest:
    """A redacted provider request whose plaintext can be consumed once."""

    __slots__ = ("context", "provider_cursor", "_credentials")

    def __init__(
        self,
        *,
        context: XianyuSyncExecutionContext,
        provider_cursor: str | None,
        credentials: Mapping[str, str],
    ) -> None:
        if (
            not isinstance(context, XianyuSyncExecutionContext)
            or not isinstance(credentials, Mapping)
            or set(credentials) != {"app_key", "app_secret"}
            or any(
                not isinstance(value, str) or not value
                for value in credentials.values()
            )
        ):
            raise XianyuSyncCredentialInputError()
        self.context = context
        self.provider_cursor = _cursor(provider_cursor)
        self._credentials: dict[str, str] | None = dict(credentials)

    def take_credentials(self) -> Mapping[str, str]:
        """Consume plaintext exactly once inside the immediate provider call."""

        credentials = self._credentials
        if credentials is None:
            raise XianyuSyncCredentialError()
        self._credentials = None
        return MappingProxyType(credentials)

    def discard_credentials(self) -> None:
        self._credentials = None

    def __repr__(self) -> str:
        state = "available" if self._credentials is not None else "consumed"
        return (
            "XianyuSyncProviderRequest("
            f"integration_uuid={self.context.integration_uuid!r}, "
            f"secret_revision_uuid={self.context.secret_revision_uuid!r}, "
            f"state={state!r}, provider_cursor=<redacted>, "
            "credentials=<redacted>)"
        )


class XianyuSyncCredentialFactory:
    """Prepare one current exact-revision request in a caller transaction."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def prepare(
        self,
        *,
        tenant_uuid: str | UUID,
        integration_uuid: str | UUID,
        secret_revision_uuid: str | UUID,
        integration_row_version: int,
        revision_row_version: int,
        provider_cursor: str | None,
        root_key_ring: RootKeyRing,
    ) -> XianyuSyncProviderRequest:
        self._require_transaction()
        tenant_id = _uuid(tenant_uuid)
        integration_id = _uuid(integration_uuid)
        revision_id = _uuid(secret_revision_uuid)
        expected_integration_version = _positive(integration_row_version)
        expected_revision_version = _positive(revision_row_version)
        selected_cursor = _cursor(provider_cursor)
        if not isinstance(root_key_ring, RootKeyRing):
            raise XianyuSyncCredentialInputError()

        try:
            pair = self._session.execute(
                sa.select(TenantIntegration, TenantIntegrationSecretRevision)
                .join(
                    TenantIntegrationSecretRevision,
                    TenantIntegrationSecretRevision.id == revision_id,
                )
                .where(
                    TenantIntegration.id == integration_id,
                    TenantIntegration.tenant_id == tenant_id,
                    TenantIntegration.provider == "xianyu",
                    TenantIntegration.status == "active",
                    TenantIntegration.current_secret_revision_id == revision_id,
                    TenantIntegration.row_version == expected_integration_version,
                    TenantIntegrationSecretRevision.tenant_integration_id
                    == integration_id,
                    TenantIntegrationSecretRevision.tenant_id == tenant_id,
                    TenantIntegrationSecretRevision.provider == "xianyu",
                    TenantIntegrationSecretRevision.status == "current",
                    TenantIntegrationSecretRevision.verification_status
                    == "succeeded",
                    TenantIntegrationSecretRevision.row_version
                    == expected_revision_version,
                )
                .with_for_update()
            ).one_or_none()
            if pair is None:
                raise XianyuSyncCredentialError()
            integration, revision = pair
            root_key = root_key_ring.key_for_existing_reference(
                revision.root_key_version
            )
            context = XianyuSyncExecutionContext(
                tenant_uuid=integration.tenant_id,
                integration_uuid=integration.id,
                secret_revision_uuid=revision.id,
                integration_row_version=integration.row_version,
                revision_row_version=revision.row_version,
            )
            return TenantIntegrationService(self._session).use_exact_revision(
                revision_uuid=revision.id,
                root_key=root_key,
                consumer=lambda bundle: XianyuSyncProviderRequest(
                    context=context,
                    provider_cursor=selected_cursor,
                    credentials=bundle._provider_values(),
                ),
            )
        except XianyuSyncCredentialInputError:
            raise
        except (
            XianyuSyncCredentialError,
            IntegrationCredentialAuthenticationError,
            IntegrationCredentialUnavailableError,
            RootKeyLoadError,
        ) as exc:
            raise XianyuSyncCredentialError() from exc

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise XianyuSyncCredentialInputError()


def _uuid(value: str | UUID) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise XianyuSyncCredentialInputError() from exc


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise XianyuSyncCredentialInputError()
    return value


def _cursor(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise XianyuSyncCredentialInputError()
    return value


__all__ = [
    "XianyuSyncCredentialError",
    "XianyuSyncCredentialFactory",
    "XianyuSyncCredentialInputError",
    "XianyuSyncExecutionContext",
    "XianyuSyncProviderRequest",
]
