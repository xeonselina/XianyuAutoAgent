from __future__ import annotations

import hashlib

import pytest

from inventory_control.redemption import (
    CROCKFORD_BASE32_ALPHABET,
    REDEMPTION_CODE_ENTROPY_BITS,
    REDEMPTION_CODE_LENGTH,
    CanonicalRedemptionCode,
    InvalidRedemptionCodeError,
    canonicalize_redemption_code,
    generate_redemption_code,
    redemption_code_lookup_hash,
)


def test_generated_codes_are_canonical_and_do_not_repr_the_bearer() -> None:
    generated = {generate_redemption_code() for _ in range(128)}

    assert len(generated) == 128
    assert REDEMPTION_CODE_ENTROPY_BITS == 130
    for code in generated:
        assert len(code.value) == REDEMPTION_CODE_LENGTH
        assert set(code.value) <= set(CROCKFORD_BASE32_ALPHABET)
        assert code.value not in repr(code)


def test_canonicalization_applies_all_approved_transformations() -> None:
    canonical = "001123456789ABCDEFGHJKMNPQ"
    submitted = "ｏｏｉｌ-2345 6789\tabcdefgh-jkmnpq"

    resolved = canonicalize_redemption_code(submitted)

    assert resolved.value == canonical


@pytest.mark.parametrize(
    "submitted",
    [
        None,
        "",
        "0" * 25,
        "0" * 27,
        "0" * 25 + "U",
        "0" * 25 + "é",
        "0" * 25 + "—",
        "0" * 25 + "_",
        "0" * 25 + "\x00",
        "0" * 257,
    ],
)
def test_invalid_inputs_are_rejected_without_echo(submitted: object) -> None:
    with pytest.raises(InvalidRedemptionCodeError) as caught:
        canonicalize_redemption_code(submitted)

    assert str(caught.value) == "redemption code is invalid"
    if isinstance(submitted, str) and submitted:
        assert submitted not in str(caught.value)


def test_whitespace_and_hyphen_variants_have_one_lookup_hash() -> None:
    canonical = "0123456789ABCDEFGHJKMNPQRS"
    variant = "01234-56789 abcde-fghjk-mnpqrs"

    expected = hashlib.sha256(canonical.encode("ascii")).digest()

    assert redemption_code_lookup_hash(canonical) == expected
    assert redemption_code_lookup_hash(variant) == expected
    assert canonicalize_redemption_code(canonical).lookup_hash_hex == expected.hex()


def test_mask_and_prefix_are_non_authorizing_hints() -> None:
    code = CanonicalRedemptionCode("0123456789ABCDEFGHJKMNPQRS")

    assert code.prefix == "0123"
    assert code.masked == "0123-******************-PQRS"
    assert code.value not in code.masked
