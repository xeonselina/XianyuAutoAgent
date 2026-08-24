from __future__ import annotations

from dataclasses import asdict

import pytest

from inventory_control.crypto import (
    CryptoConfigurationError,
    ProviderAccountFingerprint,
    RootKey,
    derive_provider_account_fingerprint,
)


ROOT = RootKey(version=7, material=bytes(range(32)))


def _fingerprint(account: str, *, root=ROOT):
    return derive_provider_account_fingerprint(
        root_key=root,
        provider="sf",
        canonical_account=account,
    )


def test_fingerprint_is_stable_keyed_and_preserves_leading_zeroes():
    first = _fingerprint("0012345678")
    replay = _fingerprint("0012345678")
    without_zeroes = _fingerprint("12345678")
    other_root = _fingerprint(
        "0012345678",
        root=RootKey(version=8, material=bytes(range(1, 33))),
    )

    assert first == replay
    assert first.digest != without_zeroes.digest
    assert first.digest != other_root.digest
    assert first.provider == "sf"
    assert first.fingerprint_version == 1
    assert first.root_key_version == 7
    assert len(first.digest) == 32


def test_fingerprint_does_not_equal_plain_sha256_or_reveal_account_in_repr():
    import hashlib

    account = "00987654321"
    fingerprint = _fingerprint(account)

    assert fingerprint.digest != hashlib.sha256(account.encode("ascii")).digest()
    rendered = repr(fingerprint)
    assert account not in rendered
    assert fingerprint.digest.hex() not in rendered
    assert "<redacted>" in rendered
    assert "canonical_account" not in asdict(fingerprint)


@pytest.mark.parametrize(
    "account",
    [
        "",
        " leading",
        "trailing ",
        "contains space",
        "line\nbreak",
        "月结账号",
        "a" * 129,
    ],
)
def test_invalid_or_noncanonical_account_is_rejected_without_echo(account):
    with pytest.raises(CryptoConfigurationError) as caught:
        _fingerprint(account)
    if account:
        assert account not in str(caught.value)


def test_provider_version_and_root_key_are_strictly_typed():
    with pytest.raises(CryptoConfigurationError, match="unsupported"):
        derive_provider_account_fingerprint(
            root_key=ROOT,
            provider="kuaimai",
            canonical_account="account",
        )
    with pytest.raises(CryptoConfigurationError, match="version"):
        derive_provider_account_fingerprint(
            root_key=ROOT,
            provider="sf",
            canonical_account="account",
            fingerprint_version=2,
        )
    with pytest.raises(CryptoConfigurationError, match="root key"):
        derive_provider_account_fingerprint(
            root_key=object(),
            provider="sf",
            canonical_account="account",
        )


def test_fingerprint_value_validates_shape_and_keeps_digest_redacted():
    with pytest.raises(CryptoConfigurationError):
        ProviderAccountFingerprint(
            provider="sf",
            fingerprint_version=1,
            root_key_version=1,
            digest=b"short",
        )
