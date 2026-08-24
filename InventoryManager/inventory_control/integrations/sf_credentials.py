"""Shared exact-revision credential loader for SF provider operations."""

from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Mapping, TypeVar

from sqlalchemy.orm import Session

from inventory_control.crypto import RootKeyLoadError, RootKeyRing
from inventory_control.models import (
    TenantIntegrationSecretRevision,
    TenantProviderAccountSecretRevision,
)

from .errors import (
    IntegrationCredentialAuthenticationError,
    IntegrationCredentialUnavailableError,
)
from .provider_account_credentials import (
    ProviderAccountCredentialAuthenticationError,
)
from .provider_account_service import (
    ProviderAccountCredentialUnavailableError,
    TenantProviderAccountService,
)
from .provider_context import SfProviderExecutionContext
from .service import TenantIntegrationService


class SfExactCredentialError(RuntimeError):
    code = "SF_EXACT_CREDENTIAL_UNAVAILABLE"
    public_message = "SF credentials are unavailable"

    def __init__(self) -> None:
        super().__init__(self.public_message)


ResultT = TypeVar("ResultT")


class SfExactCredentialFactory:
    """Authenticate both exact revisions and consume them synchronously."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def use(
        self,
        *,
        context: SfProviderExecutionContext,
        root_key_ring: RootKeyRing,
        consumer: Callable[[Mapping[str, str], str], ResultT],
    ) -> ResultT:
        if (
            not isinstance(context, SfProviderExecutionContext)
            or not isinstance(root_key_ring, RootKeyRing)
            or not callable(consumer)
        ):
            raise SfExactCredentialError()
        try:
            integration_revision = self._session.get(
                TenantIntegrationSecretRevision,
                context.integration_secret_revision_uuid,
            )
            account_revision = self._session.get(
                TenantProviderAccountSecretRevision,
                context.provider_account_secret_revision_uuid,
            )
            if not _matches(context, integration_revision, account_revision):
                raise SfExactCredentialError()
            integration_key = root_key_ring.key_for_existing_reference(
                integration_revision.root_key_version
            )
            account_key = root_key_ring.key_for_existing_reference(
                account_revision.root_key_version
            )

            def with_integration(bundle):
                integration_values = MappingProxyType(
                    dict(bundle._provider_values())
                )

                def with_account(account_secret):
                    return consumer(
                        integration_values,
                        account_secret._provider_value(),
                    )

                return TenantProviderAccountService(
                    self._session
                ).use_exact_revision(
                    revision_uuid=account_revision.id,
                    root_key=account_key,
                    consumer=with_account,
                )

            return TenantIntegrationService(self._session).use_exact_revision(
                revision_uuid=integration_revision.id,
                root_key=integration_key,
                consumer=with_integration,
            )
        except SfExactCredentialError:
            raise
        except (
            IntegrationCredentialAuthenticationError,
            IntegrationCredentialUnavailableError,
            ProviderAccountCredentialAuthenticationError,
            ProviderAccountCredentialUnavailableError,
            RootKeyLoadError,
        ) as exc:
            raise SfExactCredentialError() from exc


def _matches(context, integration_revision, account_revision) -> bool:
    return bool(
        integration_revision is not None
        and account_revision is not None
        and integration_revision.id == context.integration_secret_revision_uuid
        and account_revision.id
        == context.provider_account_secret_revision_uuid
        and integration_revision.tenant_id == context.tenant_uuid
        and account_revision.tenant_id == context.tenant_uuid
        and integration_revision.provider == "sf"
        and account_revision.provider == "sf"
        and integration_revision.tenant_integration_id == context.integration_uuid
        and account_revision.integration_id == context.integration_uuid
        and account_revision.tenant_provider_account_id
        == context.provider_account_uuid
        and account_revision.provider_account_claim_id == context.global_claim_uuid
        and account_revision.activated_claim_generation == context.claim_generation
        and account_revision.target_binding_revision == context.binding_revision
        and account_revision.masked_hint == context.masked_account_hint
        and integration_revision.status in {"current", "superseded"}
        and account_revision.status in {"current", "superseded"}
        and integration_revision.verification_status == "succeeded"
        and account_revision.verification_status == "succeeded"
    )


__all__ = ["SfExactCredentialError", "SfExactCredentialFactory"]
