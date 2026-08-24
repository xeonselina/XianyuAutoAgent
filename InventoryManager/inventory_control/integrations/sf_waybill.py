"""Exact-revision one-shot credential request for SF waybill creation."""

from __future__ import annotations

import json
from datetime import datetime
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from inventory_control.crypto import RootKeyRing

from .provider_context import (
    ProviderContextError,
    SfProviderContextResolver,
    SfProviderExecutionContext,
)
from .sf_credentials import SfExactCredentialError, SfExactCredentialFactory


class SfWaybillCredentialError(RuntimeError):
    code = "SF_WAYBILL_CREDENTIAL_UNAVAILABLE"
    public_message = "SF waybill credentials are unavailable"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfCreateWaybillRequest:
    """Immutable provider facts with credentials consumable exactly once."""

    __slots__ = (
        "context",
        "shipment_uuid",
        "provider_order_id",
        "_sender_snapshot_json",
        "_receiver_snapshot_json",
        "_cargo_snapshot_json",
        "express_type_id",
        "scheduled_dispatch_at",
        "_integration_credentials",
        "_account_secret",
    )

    def __init__(
        self,
        *,
        context,
        shipment_uuid: str,
        sender_snapshot: Mapping[str, object],
        receiver_snapshot: Mapping[str, object],
        cargo_snapshot: Mapping[str, object],
        express_type_id: int,
        scheduled_dispatch_at: datetime,
        integration_credentials: Mapping[str, str],
        account_secret: str,
    ) -> None:
        shipment_id = _uuid(shipment_uuid)
        if (
            not isinstance(context, SfProviderExecutionContext)
            or context.historical is not True
            or isinstance(express_type_id, bool)
            or not isinstance(express_type_id, int)
            or express_type_id < 1
            or not isinstance(scheduled_dispatch_at, datetime)
            or scheduled_dispatch_at.tzinfo is not None
            or set(integration_credentials) != {"partner_id", "checkword"}
            or any(
                not isinstance(value, str) or not value
                for value in integration_credentials.values()
            )
            or not isinstance(account_secret, str)
            or not account_secret
        ):
            raise SfWaybillCredentialError()
        self.context = context
        self.shipment_uuid = shipment_id
        self.provider_order_id = f"sf:{context.tenant_uuid}:{shipment_id}"
        self._sender_snapshot_json = _snapshot_json(sender_snapshot)
        self._receiver_snapshot_json = _snapshot_json(receiver_snapshot)
        self._cargo_snapshot_json = _cargo_snapshot_json(cargo_snapshot)
        self.express_type_id = express_type_id
        self.scheduled_dispatch_at = scheduled_dispatch_at
        self._integration_credentials = dict(integration_credentials)
        self._account_secret = account_secret

    @property
    def sender_snapshot(self) -> Mapping[str, object]:
        return MappingProxyType(json.loads(self._sender_snapshot_json))

    @property
    def receiver_snapshot(self) -> Mapping[str, object]:
        return MappingProxyType(json.loads(self._receiver_snapshot_json))

    @property
    def cargo_snapshot(self) -> Mapping[str, object]:
        return MappingProxyType(json.loads(self._cargo_snapshot_json))

    def take_credentials(self) -> tuple[Mapping[str, str], str]:
        if self._integration_credentials is None or self._account_secret is None:
            raise SfWaybillCredentialError()
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
            "available" if self._integration_credentials is not None else "consumed"
        )
        return (
            "SfCreateWaybillRequest("
            f"shipment_uuid={self.shipment_uuid!r}, state={state!r}, "
            "sender=<redacted>, receiver=<redacted>, credentials=<redacted>)"
        )


class SfWaybillQueryRequest:
    """Provider-order query with exact credentials and no customer PII."""

    __slots__ = (
        "context",
        "shipment_uuid",
        "provider_order_id",
        "_integration_credentials",
        "_account_secret",
    )

    def __init__(
        self,
        *,
        context: SfProviderExecutionContext,
        shipment_uuid: str,
        integration_credentials: Mapping[str, str],
        account_secret: str,
    ) -> None:
        shipment_id = _uuid(shipment_uuid)
        if (
            not isinstance(context, SfProviderExecutionContext)
            or context.historical is not True
            or set(integration_credentials) != {"partner_id", "checkword"}
            or any(
                not isinstance(value, str) or not value
                for value in integration_credentials.values()
            )
            or not isinstance(account_secret, str)
            or not account_secret
        ):
            raise SfWaybillCredentialError()
        self.context = context
        self.shipment_uuid = shipment_id
        self.provider_order_id = f"sf:{context.tenant_uuid}:{shipment_id}"
        self._integration_credentials = dict(integration_credentials)
        self._account_secret = account_secret

    def take_credentials(self) -> tuple[Mapping[str, str], str]:
        if self._integration_credentials is None or self._account_secret is None:
            raise SfWaybillCredentialError()
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
            "available" if self._integration_credentials is not None else "consumed"
        )
        return (
            "SfWaybillQueryRequest("
            f"shipment_uuid={self.shipment_uuid!r}, state={state!r}, "
            "credentials=<redacted>)"
        )


class SfWaybillCredentialFactory:
    """Build a create request from shipment-frozen credential references."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def prepare_create(
        self,
        *,
        tenant_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        integration_uuid: str | UUID,
        provider_account_uuid: str | UUID,
        integration_secret_revision_uuid: str | UUID,
        provider_account_secret_revision_uuid: str | UUID,
        binding_revision: int,
        shipment_uuid: str | UUID,
        sender_snapshot: Mapping[str, object],
        receiver_snapshot: Mapping[str, object],
        cargo_snapshot: Mapping[str, object],
        express_type_id: int,
        scheduled_dispatch_at: datetime,
        root_key_ring: RootKeyRing,
    ) -> SfCreateWaybillRequest:
        try:
            context = SfProviderContextResolver(self._session).resolve_historical(
                tenant_uuid=tenant_uuid,
                warehouse_uuid=warehouse_uuid,
                binding_revision=binding_revision,
                integration_secret_revision_uuid=integration_secret_revision_uuid,
                provider_account_secret_revision_uuid=(
                    provider_account_secret_revision_uuid
                ),
            )
            if (
                context.integration_uuid != _uuid(integration_uuid)
                or context.provider_account_uuid != _uuid(provider_account_uuid)
            ):
                raise SfWaybillCredentialError()
            return SfExactCredentialFactory(self._session).use(
                context=context,
                root_key_ring=root_key_ring,
                consumer=lambda credentials, account_secret: SfCreateWaybillRequest(
                    context=context,
                    shipment_uuid=_uuid(shipment_uuid),
                    sender_snapshot=sender_snapshot,
                    receiver_snapshot=receiver_snapshot,
                    cargo_snapshot=cargo_snapshot,
                    express_type_id=express_type_id,
                    scheduled_dispatch_at=scheduled_dispatch_at,
                    integration_credentials=credentials,
                    account_secret=account_secret,
                ),
            )
        except SfWaybillCredentialError:
            raise
        except (ProviderContextError, SfExactCredentialError, TypeError, ValueError):
            raise SfWaybillCredentialError() from None

    def prepare_query(
        self,
        *,
        tenant_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        integration_uuid: str | UUID,
        provider_account_uuid: str | UUID,
        integration_secret_revision_uuid: str | UUID,
        provider_account_secret_revision_uuid: str | UUID,
        binding_revision: int,
        shipment_uuid: str | UUID,
        root_key_ring: RootKeyRing,
    ) -> SfWaybillQueryRequest:
        try:
            context = SfProviderContextResolver(self._session).resolve_historical(
                tenant_uuid=tenant_uuid,
                warehouse_uuid=warehouse_uuid,
                binding_revision=binding_revision,
                integration_secret_revision_uuid=integration_secret_revision_uuid,
                provider_account_secret_revision_uuid=(
                    provider_account_secret_revision_uuid
                ),
            )
            if (
                context.integration_uuid != _uuid(integration_uuid)
                or context.provider_account_uuid != _uuid(provider_account_uuid)
            ):
                raise SfWaybillCredentialError()
            return SfExactCredentialFactory(self._session).use(
                context=context,
                root_key_ring=root_key_ring,
                consumer=lambda credentials, account_secret: (
                    SfWaybillQueryRequest(
                        context=context,
                        shipment_uuid=_uuid(shipment_uuid),
                        integration_credentials=credentials,
                        account_secret=account_secret,
                    )
                ),
            )
        except SfWaybillCredentialError:
            raise
        except (ProviderContextError, SfExactCredentialError, TypeError, ValueError):
            raise SfWaybillCredentialError() from None


def _snapshot_json(value: Mapping[str, object]) -> str:
    if not isinstance(value, Mapping):
        raise SfWaybillCredentialError()
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise SfWaybillCredentialError() from None
    if len(encoded.encode("utf-8")) > 16384:
        raise SfWaybillCredentialError()
    if not isinstance(json.loads(encoded), dict):
        raise SfWaybillCredentialError()
    return encoded


def _cargo_snapshot_json(value: Mapping[str, object]) -> str:
    encoded = _snapshot_json(value)
    decoded = json.loads(encoded)
    items = decoded.get("items")
    if (
        not isinstance(items, list)
        or len(items) != 1
        or not isinstance(items[0], dict)
        or set(items[0]) != {"name", "count"}
        or not isinstance(items[0]["name"], str)
        or not items[0]["name"].strip()
        or items[0]["name"] != items[0]["name"].strip()
        or len(items[0]["name"]) > 64
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in items[0]["name"]
        )
        or not isinstance(items[0]["count"], int)
        or items[0]["count"] != 1
        or isinstance(items[0]["count"], bool)
    ):
        raise SfWaybillCredentialError()
    return encoded


def _uuid(value: str | UUID) -> str:
    try:
        parsed = value if isinstance(value, UUID) else UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise SfWaybillCredentialError() from None
    if parsed.int == 0:
        raise SfWaybillCredentialError()
    return str(parsed)


__all__ = [
    "SfCreateWaybillRequest",
    "SfWaybillCredentialError",
    "SfWaybillCredentialFactory",
    "SfWaybillQueryRequest",
]
