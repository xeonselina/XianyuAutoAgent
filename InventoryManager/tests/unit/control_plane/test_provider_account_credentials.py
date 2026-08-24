from __future__ import annotations

from dataclasses import replace

import pytest

from inventory_control.crypto import RootKey, derive_provider_account_fingerprint
from inventory_control.integrations import (
    ACCOUNT_AAD_VERSION,
    ACCOUNT_CRYPTO_VERSION,
    ACCOUNT_SECRET_BUNDLE_VERSION,
    ACCOUNT_SECRET_SCHEMA_VERSION,
    ProviderAccountCredentialAuthenticationError,
    ProviderAccountCredentialInputError,
    ProviderAccountSecretCryptoContext,
    canonicalize_sf_account_secret,
    decrypt_provider_account_secret,
    encrypt_provider_account_secret,
    validate_account_fingerprint,
)


ROOT_KEY = RootKey(version=7, material=b"r" * 32)
ACCOUNT = "001234567890"
TENANT_UUID = "11111111-1111-4111-8111-111111111111"
ACCOUNT_UUID = "22222222-2222-4222-8222-222222222222"
INTEGRATION_UUID = "33333333-3333-4333-8333-333333333333"
CLAIM_UUID = "44444444-4444-4444-8444-444444444444"
CONTEXT_UUID = "55555555-5555-4555-8555-555555555555"


def _facts():
    secret = canonicalize_sf_account_secret(ACCOUNT)
    fingerprint = derive_provider_account_fingerprint(
        root_key=ROOT_KEY,
        provider="sf",
        canonical_account=secret._provider_value(),
    )
    context = ProviderAccountSecretCryptoContext(
        crypto_context_uuid=CONTEXT_UUID,
        tenant_uuid=TENANT_UUID,
        provider="sf",
        provider_account_uuid=ACCOUNT_UUID,
        integration_uuid=INTEGRATION_UUID,
        revision_no=1,
        account_secret_schema_version=ACCOUNT_SECRET_SCHEMA_VERSION,
        account_secret_bundle_version=ACCOUNT_SECRET_BUNDLE_VERSION,
        canonical_semantics_digest=secret.canonical_semantics_digest,
        provider_account_claim_uuid=CLAIM_UUID,
        account_fingerprint=fingerprint.digest,
        fingerprint_version=fingerprint.fingerprint_version,
        fingerprint_root_key_version=fingerprint.root_key_version,
        expected_claim_generation=2,
        root_key_version=ROOT_KEY.version,
        crypto_version=ACCOUNT_CRYPTO_VERSION,
        aad_version=ACCOUNT_AAD_VERSION,
    )
    return secret, fingerprint, context


def test_account_secret_round_trip_preserves_zeroes_and_redacts_representations():
    secret, fingerprint, context = _facts()
    envelope = encrypt_provider_account_secret(
        root_key=ROOT_KEY,
        context=context,
        secret=secret,
    )
    restored = decrypt_provider_account_secret(
        root_key=ROOT_KEY,
        context=context,
        envelope=envelope,
    )

    assert restored._provider_value() == ACCOUNT
    assert restored.masked_hint == "****7890"
    assert ACCOUNT not in repr(secret)
    assert ACCOUNT not in repr(restored)
    assert fingerprint.digest.hex() not in repr(context)
    assert context.purpose == "inventory-manager/tenant-provider-account/sf/v1"
    validate_account_fingerprint(context=context, fingerprint=fingerprint)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_uuid", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ("provider_account_uuid", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ("integration_uuid", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        ("provider_account_claim_uuid", "dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        ("revision_no", 2),
        ("expected_claim_generation", 3),
        ("account_fingerprint", b"x" * 32),
    ],
)
def test_authenticated_context_substitution_fails_closed(field, value):
    secret, _, context = _facts()
    envelope = encrypt_provider_account_secret(
        root_key=ROOT_KEY,
        context=context,
        secret=secret,
    )

    with pytest.raises(ProviderAccountCredentialAuthenticationError):
        decrypt_provider_account_secret(
            root_key=ROOT_KEY,
            context=replace(context, **{field: value}),
            envelope=envelope,
        )


def test_wrong_root_and_mismatched_fingerprint_fail_without_secret_echo():
    secret, fingerprint, context = _facts()
    envelope = encrypt_provider_account_secret(
        root_key=ROOT_KEY,
        context=context,
        secret=secret,
    )
    wrong_root = RootKey(version=7, material=b"w" * 32)
    other_fingerprint = derive_provider_account_fingerprint(
        root_key=wrong_root,
        provider="sf",
        canonical_account=ACCOUNT,
    )

    with pytest.raises(ProviderAccountCredentialAuthenticationError) as caught:
        decrypt_provider_account_secret(
            root_key=wrong_root,
            context=context,
            envelope=envelope,
        )
    assert ACCOUNT not in str(caught.value)
    with pytest.raises(ProviderAccountCredentialInputError):
        validate_account_fingerprint(
            context=context,
            fingerprint=other_fingerprint,
        )
    assert fingerprint.digest != other_fingerprint.digest


@pytest.mark.parametrize(
    "value",
    ["", " 001", "001 ", "contains space", "line\nbreak", "月结账号", "x" * 129],
)
def test_noncanonical_input_is_rejected_without_echo(value):
    with pytest.raises(ProviderAccountCredentialInputError) as caught:
        canonicalize_sf_account_secret(value)
    if value:
        assert value not in str(caught.value)


def test_short_account_hint_never_reveals_the_entire_value():
    assert canonicalize_sf_account_secret("1234").masked_hint == "****"
