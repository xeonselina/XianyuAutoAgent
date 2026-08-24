import hashlib

import pytest

from inventory_control.evidence import (
    canonical_json_bytes,
    canonical_json_sha256,
    require_sha256_digest,
)


class _EvidenceError(RuntimeError):
    pass


def test_canonical_json_bytes_is_compact_sorted_ascii() -> None:
    encoded = canonical_json_bytes({"z": "租", "a": [2, 1]})

    assert encoded == b'{"a":[2,1],"z":"\\u79df"}'
    assert (
        canonical_json_sha256({"z": "租", "a": [2, 1]})
        == hashlib.sha256(encoded).digest()
    )


def test_canonical_json_bytes_supports_utf8_evidence_contract() -> None:
    assert canonical_json_bytes({"value": "租"}, ensure_ascii=False) == (
        '{"value":"租"}'.encode("utf-8")
    )


def test_canonical_json_bytes_translates_invalid_payload() -> None:
    with pytest.raises(_EvidenceError):
        canonical_json_bytes(
            {"invalid": object()},
            invalid_error=_EvidenceError,
        )


def test_sha256_digest_validation_preserves_bytes_and_domain_error() -> None:
    digest = bytes(range(32))

    assert require_sha256_digest(digest, _EvidenceError) is digest
    with pytest.raises(_EvidenceError):
        require_sha256_digest(digest[:-1], _EvidenceError)
