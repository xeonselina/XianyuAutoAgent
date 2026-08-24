"""One-shot credential bridge for historical SF tracking queries.

This module performs no provider I/O.  It resolves and authenticates only the
two immutable revisions named by a shipment batch, then hands a redacted,
single-consumption request to an outer adapter after the control transaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from inventory_control.crypto import RootKeyRing

from .provider_context import (
    ProviderContextError,
    SfProviderContextResolver,
    SfProviderExecutionContext,
)
from .sf_credentials import SfExactCredentialError, SfExactCredentialFactory


_PHONE_LAST4 = re.compile(r"^\d{4}$")
_MAX_BATCH_SIZE = 100


class HistoricalTrackingCredentialError(RuntimeError):
    code = "SF_HISTORICAL_TRACKING_CREDENTIAL_UNAVAILABLE"
    public_message = "historical tracking credentials are unavailable"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class HistoricalTrackingCredentialInputError(HistoricalTrackingCredentialError):
    code = "SF_HISTORICAL_TRACKING_INPUT_INVALID"
    public_message = "historical tracking request is invalid"


@dataclass(frozen=True, slots=True)
class SfTrackingQueryItem:
    shipment_uuid: str
    waybill_no: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "shipment_uuid", _uuid(self.shipment_uuid))
        if (
            not isinstance(self.waybill_no, str)
            or not self.waybill_no
            or self.waybill_no != self.waybill_no.strip()
            or len(self.waybill_no) > 64
            or any(ord(character) < 0x20 for character in self.waybill_no)
        ):
            raise HistoricalTrackingCredentialInputError()


class SfHistoricalTrackingRequest:
    """Single-consumption request whose representation never exposes secrets."""

    __slots__ = (
        "context",
        "phone_last4",
        "items",
        "_integration_credentials",
        "_account_secret",
    )

    def __init__(
        self,
        *,
        context: SfProviderExecutionContext,
        phone_last4: str,
        items: Sequence[SfTrackingQueryItem],
        integration_credentials: Mapping[str, str],
        account_secret: str,
    ) -> None:
        selected_items = tuple(items)
        if (
            not isinstance(context, SfProviderExecutionContext)
            or context.historical is not True
            or not isinstance(phone_last4, str)
            or _PHONE_LAST4.fullmatch(phone_last4) is None
            or not selected_items
            or len(selected_items) > _MAX_BATCH_SIZE
            or any(
                not isinstance(item, SfTrackingQueryItem)
                for item in selected_items
            )
            or len({item.shipment_uuid for item in selected_items})
            != len(selected_items)
            or len({item.waybill_no for item in selected_items})
            != len(selected_items)
            or not isinstance(integration_credentials, Mapping)
            or set(integration_credentials) != {"partner_id", "checkword"}
            or any(
                not isinstance(value, str) or not value
                for value in integration_credentials.values()
            )
            or not isinstance(account_secret, str)
            or not account_secret
        ):
            raise HistoricalTrackingCredentialInputError()
        self.context = context
        self.phone_last4 = phone_last4
        self.items = selected_items
        self._integration_credentials = dict(integration_credentials)
        self._account_secret = account_secret

    def take_credentials(self) -> tuple[Mapping[str, str], str]:
        """Consume plaintext exactly once inside the immediate provider call."""

        if (
            self._integration_credentials is None
            or self._account_secret is None
        ):
            raise HistoricalTrackingCredentialError()
        credentials = MappingProxyType(self._integration_credentials)
        account_secret = self._account_secret
        self._integration_credentials = None
        self._account_secret = None
        return credentials, account_secret

    def discard_credentials(self) -> None:
        self._integration_credentials = None
        self._account_secret = None

    def __repr__(self) -> str:
        state = (
            "available"
            if self._integration_credentials is not None
            else "consumed"
        )
        return (
            "SfHistoricalTrackingRequest("
            f"shipment_count={len(self.items)}, state={state!r}, "
            "credentials=<redacted>)"
        )


class SfHistoricalTrackingCredentialFactory:
    """Prepare one exact-revision request in a caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def prepare(
        self,
        *,
        tenant_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        integration_uuid: str | UUID,
        provider_account_uuid: str | UUID,
        integration_secret_revision_uuid: str | UUID,
        provider_account_secret_revision_uuid: str | UUID,
        binding_revision: int,
        phone_last4: str,
        items: Sequence[SfTrackingQueryItem],
        root_key_ring: RootKeyRing,
    ) -> SfHistoricalTrackingRequest:
        tenant_id = _uuid(tenant_uuid)
        warehouse_id = _uuid(warehouse_uuid)
        integration_id = _uuid(integration_uuid)
        account_id = _uuid(provider_account_uuid)
        integration_revision_id = _uuid(integration_secret_revision_uuid)
        account_revision_id = _uuid(provider_account_secret_revision_uuid)
        if (
            not isinstance(binding_revision, int)
            or isinstance(binding_revision, bool)
            or binding_revision < 1
            or not isinstance(root_key_ring, RootKeyRing)
        ):
            raise HistoricalTrackingCredentialInputError()
        try:
            context = SfProviderContextResolver(
                self._session
            ).resolve_historical(
                tenant_uuid=tenant_id,
                warehouse_uuid=warehouse_id,
                binding_revision=binding_revision,
                integration_secret_revision_uuid=integration_revision_id,
                provider_account_secret_revision_uuid=account_revision_id,
            )
            if (
                context.integration_uuid != integration_id
                or context.provider_account_uuid != account_id
                or context.integration_secret_revision_uuid
                != integration_revision_id
                or context.provider_account_secret_revision_uuid
                != account_revision_id
            ):
                raise HistoricalTrackingCredentialError()
            return SfExactCredentialFactory(self._session).use(
                context=context,
                root_key_ring=root_key_ring,
                consumer=lambda credentials, account_secret: (
                    SfHistoricalTrackingRequest(
                        context=context,
                        phone_last4=phone_last4,
                        items=items,
                        integration_credentials=credentials,
                        account_secret=account_secret,
                    )
                ),
            )
        except HistoricalTrackingCredentialInputError:
            raise
        except (
            HistoricalTrackingCredentialError,
            SfExactCredentialError,
            ProviderContextError,
        ) as exc:
            raise HistoricalTrackingCredentialError() from exc


def _uuid(value: str | UUID) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise HistoricalTrackingCredentialInputError() from exc


__all__ = [
    "HistoricalTrackingCredentialError",
    "HistoricalTrackingCredentialInputError",
    "SfHistoricalTrackingCredentialFactory",
    "SfHistoricalTrackingRequest",
    "SfTrackingQueryItem",
]
