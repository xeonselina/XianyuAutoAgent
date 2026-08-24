import base64
import hashlib

import pytest

from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    TOKEN_DIGEST_BYTES,
    TOKEN_ENTROPY_BITS,
    InvalidOpaqueTokenError,
    PhoneIdentityNormalizer,
    PhoneNormalizationError,
    digest_csrf_token,
    digest_session_token,
    issue_csrf_token,
    issue_session_token,
    normalize_tenant_phone,
    verify_csrf_token,
    verify_session_token,
)


@pytest.mark.parametrize(
    "raw_phone",
    [
        "13800138000",
        "+8613800138000",
        "138 0013 8000",
        "138-0013-8000",
        "+86 138-0013-8000",
        "+8-6 138 0013 8000",
    ],
)
def test_phone_normalizer_maps_supported_equivalents_to_one_e164_value(raw_phone):
    assert normalize_tenant_phone(raw_phone) == "+8613800138000"


@pytest.mark.parametrize(
    "raw_phone",
    [
        "13123456789",
        "14512345678",
        "16212345678",
        "16100123456",
        "17400123456",
        "19912345678",
    ],
)
def test_phone_normalizer_accepts_versioned_mainland_mobile_metadata(raw_phone):
    normalizer = PhoneIdentityNormalizer()

    assert normalizer.normalize(raw_phone) == "+86" + raw_phone
    assert normalizer.normalization_version == PHONE_NORMALIZATION_VERSION == 1
    assert normalizer.metadata_version == CN_MOBILE_METADATA_VERSION


@pytest.mark.parametrize(
    "raw_phone",
    [
        None,
        b"13800138000",
        "",
        "008613800138000",
        "8613800138000",
        "+1 202-555-0123",
        "+852 5123 4567",
        "+853 6612 3456",
        "+886 912 345 678",
        "01012345678",
        "12345",
        "12800138000",
        "15400138000",
        "16110138000",
        "17406138000",
        "19400138000",
        "１３８００１３８０００",
        "١٣٨٠٠١٣٨٠٠٠",
        "(138)0013-8000",
        "13800138000 ext 1",
        "13800138000x1",
        "138\t0013\t8000",
        "138\u00a00013\u00a08000",
        "138‑0013‑8000",
    ],
)
def test_phone_normalizer_rejects_unsupported_or_ambiguous_input(raw_phone):
    with pytest.raises(PhoneNormalizationError) as caught:
        normalize_tenant_phone(raw_phone)

    assert caught.value.code == "PHONE_IDENTITY_INVALID"
    assert "account" not in str(caught.value).lower()
    assert "exist" not in str(caught.value).lower()
    if isinstance(raw_phone, str) and raw_phone:
        assert raw_phone not in str(caught.value)


def _decode_random_part(token):
    encoded = token.plaintext.split("_", 1)[1]
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def test_session_and_csrf_tokens_have_independent_256_bit_random_material():
    session = issue_session_token()
    csrf = issue_csrf_token()

    assert TOKEN_ENTROPY_BITS == 256
    assert len(_decode_random_part(session)) == 32
    assert len(_decode_random_part(csrf)) == 32
    assert session.plaintext != csrf.plaintext
    assert session.digest_sha256 != csrf.digest_sha256
    assert session.plaintext.startswith("ims1_")
    assert csrf.plaintext.startswith("imc1_")


def test_only_sha256_digest_is_exposed_for_persistence_and_repr_is_redacted():
    session = issue_session_token()
    csrf = issue_csrf_token()

    assert TOKEN_DIGEST_BYTES == 32
    assert session.digest_sha256 == hashlib.sha256(
        session.plaintext.encode("ascii")
    ).digest()
    assert csrf.digest_sha256 == hashlib.sha256(
        csrf.plaintext.encode("ascii")
    ).digest()
    assert digest_session_token(session.plaintext) == session.digest_sha256
    assert digest_csrf_token(csrf.plaintext) == csrf.digest_sha256
    assert session.plaintext not in repr(session)
    assert csrf.plaintext not in repr(csrf)


def test_session_and_csrf_tokens_cannot_cross_identity_namespaces():
    session = issue_session_token()
    csrf = issue_csrf_token()

    assert verify_session_token(session.plaintext, session.digest_sha256)
    assert verify_csrf_token(csrf.plaintext, csrf.digest_sha256)
    assert not verify_session_token(csrf.plaintext, csrf.digest_sha256)
    assert not verify_csrf_token(session.plaintext, session.digest_sha256)

    with pytest.raises(InvalidOpaqueTokenError):
        digest_session_token(csrf.plaintext)
    with pytest.raises(InvalidOpaqueTokenError):
        digest_csrf_token(session.plaintext)


@pytest.mark.parametrize(
    ("presented", "digest"),
    [
        ("not-a-session-token", bytes(32)),
        (None, bytes(32)),
        (123, bytes(32)),
        ("ims1_" + "A" * 43, b"short"),
        ("ims1_" + "A" * 43, None),
    ],
)
def test_invalid_session_proofs_return_one_non_disclosing_result(presented, digest):
    assert verify_session_token(presented, digest) is False


def test_token_verification_uses_constant_time_digest_comparison(monkeypatch):
    issued = issue_session_token()
    calls = []

    def recording_compare_digest(candidate, stored):
        calls.append((candidate, stored))
        return candidate == stored

    monkeypatch.setattr(
        "inventory_control.identity.tokens.hmac.compare_digest",
        recording_compare_digest,
    )

    assert verify_session_token(issued.plaintext, issued.digest_sha256)
    assert verify_session_token("malformed", b"short") is False
    assert len(calls) == 2
    assert all(len(candidate) == len(stored) == 32 for candidate, stored in calls)


def test_invalid_token_errors_are_fixed_and_do_not_echo_credentials():
    sensitive_value = "ims1_private-account-marker"

    with pytest.raises(InvalidOpaqueTokenError) as caught:
        digest_session_token(sensitive_value)

    assert caught.value.code == "IDENTITY_CREDENTIAL_INVALID"
    assert sensitive_value not in str(caught.value)
    assert "account" not in str(caught.value).lower()
    assert "exist" not in str(caught.value).lower()
