"""Root-key envelope rotation for immutable provider-account revisions."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.crypto import CryptoCodecV1, EncryptedEnvelope, RootKey
from inventory_control.models import (
    TenantProviderAccountSecretEnvelopeEvent,
    TenantProviderAccountSecretRevision,
)
from inventory_control.transactions import require_caller_transaction

from .provider_account_credentials import (
    ProviderAccountSecretCryptoContext,
    decrypt_provider_account_secret,
    encrypt_provider_account_secret,
)
from .provider_account_service import (
    ProviderAccountIdempotencyConflictError,
    ProviderAccountInputError,
    ProviderAccountPersistenceError,
    ProviderAccountStateConflictError,
    ProviderAccountTransactionError,
)


@dataclass(frozen=True, slots=True)
class ProviderAccountEnvelopeRotationRef:
    event_uuid: str
    revision_uuid: str
    envelope_generation: int
    from_root_key_version: int
    to_root_key_version: int
    idempotent_replay: bool = False


class TenantProviderAccountEnvelopeService:
    """Rewrap one exact business revision without changing its semantics."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise ProviderAccountTransactionError()
        self._session = session

    def rewrap_exact_revision(
        self,
        *,
        revision_uuid: str | UUID,
        old_root_key: RootKey,
        new_root_key: RootKey,
        rotation_run_uuid: str | UUID,
        rotation_action_uuid: str | UUID,
        idempotency_key: str,
        expected_envelope_row_version: int,
    ) -> ProviderAccountEnvelopeRotationRef:
        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        run_id = _uuid(rotation_run_uuid)
        action_id = _uuid(rotation_action_uuid)
        request_key = _technical_key(idempotency_key)
        expected_version = _positive(expected_envelope_row_version)
        if (
            not isinstance(old_root_key, RootKey)
            or not isinstance(new_root_key, RootKey)
            or new_root_key.version <= old_root_key.version
        ):
            raise ProviderAccountInputError()
        request_digest = _request_digest(
            revision_id=revision_id,
            run_id=run_id,
            action_id=action_id,
            request_key=request_key,
            expected_version=expected_version,
            old_root_version=old_root_key.version,
            new_root_version=new_root_key.version,
        )
        existing = self._session.scalar(
            sa.select(TenantProviderAccountSecretEnvelopeEvent)
            .where(
                TenantProviderAccountSecretEnvelopeEvent.idempotency_key == request_key
            )
            .with_for_update()
        )
        if existing is not None:
            return _replay(
                existing,
                revision_id=revision_id,
                request_digest=request_digest,
                new_root_version=new_root_key.version,
            )
        revision = self._session.scalar(
            sa.select(TenantProviderAccountSecretRevision)
            .where(TenantProviderAccountSecretRevision.id == revision_id)
            .with_for_update()
        )
        if (
            revision is None
            or revision.status not in ("current", "superseded")
            or revision.verification_status != "succeeded"
            or revision.envelope_row_version != expected_version
            or revision.envelope_generation != expected_version
            or revision.root_key_version != old_root_key.version
        ):
            raise ProviderAccountStateConflictError()
        secret = decrypt_provider_account_secret(
            root_key=old_root_key,
            context=_context(revision),
            envelope=_envelope(revision),
        )
        new_context = _context(
            revision,
            root_key_version=new_root_key.version,
        )
        new_envelope = encrypt_provider_account_secret(
            root_key=new_root_key,
            context=new_context,
            secret=secret,
        )
        next_generation = revision.envelope_generation + 1
        event = TenantProviderAccountSecretEnvelopeEvent(
            id=str(uuid4()),
            tenant_provider_account_secret_revision_id=revision.id,
            envelope_generation=next_generation,
            from_root_key_version=revision.root_key_version,
            to_root_key_version=new_root_key.version,
            from_crypto_version=revision.crypto_version,
            to_crypto_version=new_envelope.crypto_version,
            from_aad_version=revision.aad_version,
            to_aad_version=new_envelope.aad_version,
            before_ciphertext_digest=hashlib.sha256(
                bytes(revision.account_secret_ciphertext)
            ).digest(),
            after_ciphertext_digest=hashlib.sha256(new_envelope.ciphertext).digest(),
            rotation_run_uuid=run_id,
            rotation_action_uuid=action_id,
            idempotency_key=request_key,
            request_digest=request_digest,
            safe_outcome="succeeded",
        )
        try:
            with self._session.begin_nested():
                changed = self._session.execute(
                    sa.update(TenantProviderAccountSecretRevision)
                    .where(
                        TenantProviderAccountSecretRevision.id == revision.id,
                        TenantProviderAccountSecretRevision.envelope_row_version
                        == expected_version,
                        TenantProviderAccountSecretRevision.root_key_version
                        == old_root_key.version,
                    )
                    .values(
                        account_secret_ciphertext=new_envelope.ciphertext,
                        account_secret_nonce=new_envelope.nonce,
                        root_key_version=new_envelope.root_key_version,
                        crypto_version=new_envelope.crypto_version,
                        aad_version=new_envelope.aad_version,
                        envelope_generation=next_generation,
                        envelope_row_version=next_generation,
                        last_envelope_rotation_event_id=event.id,
                        row_version=revision.row_version + 1,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise ProviderAccountStateConflictError()
                self._session.add(event)
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            winner = self._session.scalar(
                sa.select(TenantProviderAccountSecretEnvelopeEvent).where(
                    TenantProviderAccountSecretEnvelopeEvent.idempotency_key
                    == request_key
                )
            )
            if winner is None:
                raise ProviderAccountPersistenceError() from None
            return _replay(
                winner,
                revision_id=revision_id,
                request_digest=request_digest,
                new_root_version=new_root_key.version,
            )
        return _ref(event)

    def _require_transaction(self) -> None:
        require_caller_transaction(
            self._session,
            ProviderAccountTransactionError,
        )


def _context(revision, *, root_key_version=None):
    return ProviderAccountSecretCryptoContext(
        crypto_context_uuid=revision.crypto_context_uuid,
        tenant_uuid=revision.tenant_id,
        provider=revision.provider,
        provider_account_uuid=revision.tenant_provider_account_id,
        integration_uuid=revision.integration_id,
        revision_no=revision.revision_no,
        account_secret_schema_version=revision.account_secret_schema_version,
        account_secret_bundle_version=revision.account_secret_bundle_version,
        canonical_semantics_digest=bytes(revision.canonical_semantics_digest),
        provider_account_claim_uuid=revision.provider_account_claim_id,
        account_fingerprint=bytes(revision.account_fingerprint),
        fingerprint_version=revision.fingerprint_version,
        fingerprint_root_key_version=revision.fingerprint_root_key_version,
        expected_claim_generation=revision.expected_claim_generation,
        root_key_version=(
            revision.root_key_version if root_key_version is None else root_key_version
        ),
        crypto_version=revision.crypto_version,
        aad_version=revision.aad_version,
    )


def _envelope(revision):
    return EncryptedEnvelope(
        nonce=bytes(revision.account_secret_nonce),
        ciphertext=bytes(revision.account_secret_ciphertext),
        root_key_version=revision.root_key_version,
        crypto_version=revision.crypto_version,
        aad_version=revision.aad_version,
    )


def _request_digest(
    *,
    revision_id,
    run_id,
    action_id,
    request_key,
    expected_version,
    old_root_version,
    new_root_version,
):
    return hashlib.sha256(
        b"".join(
            (
                b"inventory-manager/provider-account-envelope-rotation/v1\x00",
                CryptoCodecV1.uuid_bytes(revision_id),
                CryptoCodecV1.uuid_bytes(run_id),
                CryptoCodecV1.uuid_bytes(action_id),
                CryptoCodecV1.ascii_text(request_key),
                CryptoCodecV1.uint64(expected_version),
                CryptoCodecV1.uint64(old_root_version),
                CryptoCodecV1.uint64(new_root_version),
            )
        )
    ).digest()


def _replay(event, *, revision_id, request_digest, new_root_version):
    if (
        event.tenant_provider_account_secret_revision_id != revision_id
        or event.to_root_key_version != new_root_version
        or bytes(event.request_digest) != request_digest
    ):
        raise ProviderAccountIdempotencyConflictError()
    return _ref(event, replay=True)


def _ref(event, *, replay=False):
    return ProviderAccountEnvelopeRotationRef(
        event_uuid=event.id,
        revision_uuid=event.tenant_provider_account_secret_revision_id,
        envelope_generation=event.envelope_generation,
        from_root_key_version=event.from_root_key_version,
        to_root_key_version=event.to_root_key_version,
        idempotent_replay=replay,
    )


def _uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise ProviderAccountInputError() from None


def _positive(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderAccountInputError()
    return value


def _technical_key(value) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= 128
        or not value.isascii()
        or any(ord(char) < 33 for char in value)
    ):
        raise ProviderAccountInputError()
    return value


__all__ = [
    "ProviderAccountEnvelopeRotationRef",
    "TenantProviderAccountEnvelopeService",
]
