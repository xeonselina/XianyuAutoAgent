from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from inventory_control.crypto import EncryptedEnvelope, RootKey
from inventory_control.integrations import (
    IntegrationCredentialAuthenticationError,
    IntegrationInputError,
    IntegrationSecretCryptoContext,
    canonicalize_provider_credentials,
    decrypt_provider_credentials,
    encrypt_provider_credentials,
)


ROOT_KEY = RootKey(version=7, material=b"r" * 32)
CONTEXT_UUID = UUID("40000000-0000-4000-8000-000000000001")
TENANT_UUID = UUID("40000000-0000-4000-8000-000000000002")
INTEGRATION_UUID = UUID("40000000-0000-4000-8000-000000000003")


def _context(bundle, **changes):
    context = IntegrationSecretCryptoContext(
        crypto_context_uuid=str(CONTEXT_UUID),
        tenant_uuid=str(TENANT_UUID),
        provider=bundle.provider,
        integration_uuid=str(INTEGRATION_UUID),
        revision_no=3,
        credential_schema_version=1,
        credential_bundle_version=1,
        canonical_semantics_digest=bundle.canonical_semantics_digest,
        root_key_version=ROOT_KEY.version,
    )
    return replace(context, **changes)


@pytest.mark.parametrize(
    ("provider", "first", "second"),
    [
        (
            "sf",
            {"partner_id": "partner-001", "checkword": "sf-secret-value"},
            {"checkword": "sf-secret-value", "partner_id": "partner-001"},
        ),
        (
            "xianyu",
            {"app_key": "xianyu-key", "app_secret": "xianyu-secret-value"},
            {"app_secret": "xianyu-secret-value", "app_key": "xianyu-key"},
        ),
        (
            "kuaimai",
            {"app_id": "kuaimai-id", "app_secret": "kuaimai-secret-value"},
            {"app_secret": "kuaimai-secret-value", "app_id": "kuaimai-id"},
        ),
    ],
)
def test_bundle_is_canonical_and_repr_is_redacted(provider, first, second):
    left = canonicalize_provider_credentials(provider, first)
    right = canonicalize_provider_credentials(provider, second)

    assert left.canonical_semantics_digest == right.canonical_semantics_digest
    rendered = repr(left)
    assert "<redacted>" in rendered
    for value in first.values():
        assert value not in rendered


def test_bundle_requires_exact_provider_keys_and_values():
    with pytest.raises(IntegrationInputError):
        canonicalize_provider_credentials(
            "sf", {"partner_id": "p", "checkword": "s", "extra": "x"}
        )
    with pytest.raises(IntegrationInputError):
        canonicalize_provider_credentials("sf", {"partner_id": "p"})
    with pytest.raises(IntegrationInputError):
        canonicalize_provider_credentials(
            "sf", {"partner_id": "p", "checkword": "line\nbreak"}
        )
    with pytest.raises(IntegrationInputError):
        canonicalize_provider_credentials(
            "SF", {"partner_id": "p", "checkword": "s"}
        )


def test_random_nonce_and_round_trip_keep_envelope_repr_nonsecret():
    secret = "never-print-this-secret"
    bundle = canonicalize_provider_credentials(
        "sf", {"partner_id": "partner", "checkword": secret}
    )
    context = _context(bundle)

    first = encrypt_provider_credentials(
        root_key=ROOT_KEY, context=context, bundle=bundle
    )
    second = encrypt_provider_credentials(
        root_key=ROOT_KEY, context=context, bundle=bundle
    )

    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert secret not in repr(first)
    recovered = decrypt_provider_credentials(
        root_key=ROOT_KEY, context=context, envelope=first
    )
    assert recovered.canonical_semantics_digest == bundle.canonical_semantics_digest


@pytest.mark.parametrize(
    "change",
    [
        {"tenant_uuid": "40000000-0000-4000-8000-000000000012"},
        {"integration_uuid": "40000000-0000-4000-8000-000000000013"},
        {"provider": "xianyu"},
        {"revision_no": 4},
        {"canonical_semantics_digest": b"z" * 32},
    ],
)
def test_authenticated_context_swap_fails_with_fixed_error(change):
    bundle = canonicalize_provider_credentials(
        "sf", {"partner_id": "partner", "checkword": "secret"}
    )
    context = _context(bundle)
    envelope = encrypt_provider_credentials(
        root_key=ROOT_KEY, context=context, bundle=bundle
    )

    with pytest.raises(IntegrationCredentialAuthenticationError) as caught:
        decrypt_provider_credentials(
            root_key=ROOT_KEY,
            context=replace(context, **change),
            envelope=envelope,
        )
    assert (
        str(caught.value)
        == "the exact credential revision could not be authenticated"
    )
    assert "secret" not in repr(caught.value)


@pytest.mark.parametrize("tamper", ["nonce", "ciphertext"])
def test_envelope_tamper_fails_without_secret_detail(tamper):
    bundle = canonicalize_provider_credentials(
        "sf", {"partner_id": "partner", "checkword": "secret"}
    )
    context = _context(bundle)
    original = encrypt_provider_credentials(
        root_key=ROOT_KEY, context=context, bundle=bundle
    )
    nonce = bytearray(original.nonce)
    ciphertext = bytearray(original.ciphertext)
    if tamper == "nonce":
        nonce[0] ^= 1
    else:
        ciphertext[-1] ^= 1
    altered = EncryptedEnvelope(
        nonce=bytes(nonce),
        ciphertext=bytes(ciphertext),
        root_key_version=original.root_key_version,
        crypto_version=original.crypto_version,
        aad_version=original.aad_version,
    )

    with pytest.raises(IntegrationCredentialAuthenticationError):
        decrypt_provider_credentials(
            root_key=ROOT_KEY, context=context, envelope=altered
        )
