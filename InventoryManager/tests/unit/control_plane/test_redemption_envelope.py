from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.crypto import (
    CryptoAuthenticationError,
    CryptoConfigurationError,
    RootKey,
    encrypt_record,
)
from inventory_control.redemption import (
    REDEMPTION_CODE_SECRET_PURPOSE,
    RedemptionCodeSecretContext,
    decrypt_redemption_code,
    encrypt_redemption_code,
)


ROOT_KEY = RootKey(version=2, material=bytes(range(32)))
CODE = "0123456789ABCDEFGHJKMNPQRS"


def _context(**changes):
    values = {
        "code_uuid": UUID("10000000-0000-4000-8000-000000000001"),
        "crypto_context_uuid": UUID("10000000-0000-4000-8000-000000000002"),
        "batch_uuid": UUID("10000000-0000-4000-8000-000000000003"),
        "plan_revision_uuid": UUID("10000000-0000-4000-8000-000000000004"),
        "entitlements_schema_version": 1,
        "entitlements_digest_sha256": bytes.fromhex("ab" * 32),
        "service_duration_seconds": 31_536_000,
        "redeem_before": datetime(2027, 1, 1, tzinfo=timezone.utc),
        "created_under_recovery_run_uuid": UUID(
            "10000000-0000-4000-8000-000000000005"
        ),
        "secret_revision": 1,
    }
    values.update(changes)
    return RedemptionCodeSecretContext(**values)


def test_redemption_envelope_round_trip_binds_all_terms() -> None:
    context = _context()

    envelope = encrypt_redemption_code(
        root_key=ROOT_KEY,
        context=context,
        code=CODE,
    )

    resolved = decrypt_redemption_code(
        root_key=ROOT_KEY,
        context=context,
        envelope=envelope,
    )
    assert resolved.value == CODE
    assert CODE not in repr(envelope)
    assert CODE not in repr(context)
    assert CODE.encode("ascii") not in envelope.ciphertext


def test_input_aliases_are_encrypted_as_the_canonical_bearer() -> None:
    context = _context()
    envelope = encrypt_redemption_code(
        root_key=ROOT_KEY,
        context=context,
        code="o1234-56789 abcdefgh-jkmnpqrs",
    )

    assert decrypt_redemption_code(
        root_key=ROOT_KEY,
        context=context,
        envelope=envelope,
    ).value == CODE


@pytest.mark.parametrize(
    "changed_context",
    [
        _context(code_uuid=UUID("20000000-0000-4000-8000-000000000001")),
        _context(crypto_context_uuid=UUID("20000000-0000-4000-8000-000000000002")),
        _context(batch_uuid=UUID("20000000-0000-4000-8000-000000000003")),
        _context(plan_revision_uuid=UUID("20000000-0000-4000-8000-000000000004")),
        _context(entitlements_schema_version=2),
        _context(entitlements_digest_sha256=bytes.fromhex("cd" * 32)),
        _context(service_duration_seconds=31_536_001),
        _context(redeem_before=datetime(2027, 1, 2, tzinfo=timezone.utc)),
        _context(
            created_under_recovery_run_uuid=UUID(
                "20000000-0000-4000-8000-000000000005"
            )
        ),
        _context(secret_revision=2),
    ],
)
def test_context_swaps_fail_authentication(changed_context) -> None:
    envelope = encrypt_redemption_code(
        root_key=ROOT_KEY,
        context=_context(),
        code=CODE,
    )

    with pytest.raises(CryptoAuthenticationError, match="authentication failed"):
        decrypt_redemption_code(
            root_key=ROOT_KEY,
            context=changed_context,
            envelope=envelope,
        )


def test_deadline_is_canonicalized_to_utc() -> None:
    context = _context(
        redeem_before=datetime(
            2027,
            1,
            1,
            8,
            tzinfo=timezone(timedelta(hours=8)),
        )
    )

    assert context.redeem_before == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert context.canonical_aad() == _context().canonical_aad()


@pytest.mark.parametrize(
    "changes",
    [
        {"entitlements_digest_sha256": b"short"},
        {"service_duration_seconds": 0},
        {"secret_revision": 0},
        {"redeem_before": datetime(2027, 1, 1)},
        {"redeem_before": datetime(1969, 1, 1, tzinfo=timezone.utc)},
    ],
)
def test_invalid_crypto_context_fails_closed(changes) -> None:
    with pytest.raises(CryptoConfigurationError):
        _context(**changes)


def test_authenticated_but_noncanonical_plaintext_is_rejected_generically() -> None:
    context = _context()
    envelope = encrypt_record(
        root_key=ROOT_KEY,
        purpose=REDEMPTION_CODE_SECRET_PURPOSE,
        record_uuid=context.crypto_context_uuid,
        revision=context.secret_revision,
        canonical_aad=context.canonical_aad(),
        plaintext=b"not-a-valid-redemption-code",
    )

    with pytest.raises(CryptoAuthenticationError) as caught:
        decrypt_redemption_code(
            root_key=ROOT_KEY,
            context=context,
            envelope=envelope,
        )

    assert "not-a-valid" not in str(caught.value)
