import base64
import uuid
from dataclasses import replace

import pytest

from inventory_control.crypto import (
    CryptoAuthenticationError,
    CryptoConfigurationError,
    EncryptedEnvelope,
    RootKey,
    RootKeyLoadError,
    decrypt_record,
    derive_platform_read_password,
    derive_tenant_dml_password,
    encrypt_record,
    load_root_key,
    root_key_fingerprint_sha256,
)


ROOT_MATERIAL = bytes(range(32))
TENANT_UUID = uuid.UUID("11111111-2222-4333-8444-555555555555")
DATABASE_UUID = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
RECORD_UUID = uuid.UUID("12345678-1234-4567-89ab-123456789abc")


@pytest.fixture
def root_key():
    return RootKey(version=7, material=ROOT_MATERIAL)


def _write_root_key(path, material=ROOT_MATERIAL, mode=0o400, newline=True):
    encoded = base64.b64encode(material) + (b"\n" if newline else b"")
    path.write_bytes(encoded)
    path.chmod(mode)


def _canonical_aad(record_uuid=RECORD_UUID, revision=3):
    return b"aad-v1:" + record_uuid.bytes + revision.to_bytes(8, "big")


def test_root_key_is_strictly_versioned_and_has_safe_fingerprint(root_key):
    assert root_key.version == 7
    assert root_key_fingerprint_sha256(root_key) == (
        "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8ab"
        "c1b8581bd710dd"
    )
    assert ROOT_MATERIAL.hex() not in repr(root_key)

    with pytest.raises(CryptoConfigurationError):
        RootKey(version=0, material=ROOT_MATERIAL)
    with pytest.raises(CryptoConfigurationError):
        RootKey(version=1, material=b"short")


@pytest.mark.parametrize("mode", [0o400, 0o440])
@pytest.mark.parametrize("newline", [False, True])
def test_load_root_key_accepts_only_supported_read_only_shapes(
    tmp_path, mode, newline
):
    key_path = tmp_path / "v7"
    _write_root_key(key_path, mode=mode, newline=newline)

    loaded = load_root_key(
        key_path,
        version=7,
        expected_fingerprint_sha256=(
            "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8ab"
            "c1b8581bd710dd"
        ),
    )

    assert loaded == RootKey(version=7, material=ROOT_MATERIAL)


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o444, 0o644, 0o777])
def test_load_root_key_rejects_permissions_that_are_too_broad(tmp_path, mode):
    key_path = tmp_path / "v1"
    _write_root_key(key_path, mode=mode)

    with pytest.raises(RootKeyLoadError, match="permissions"):
        load_root_key(key_path, version=1)


def test_load_root_key_rejects_symlink_missing_relative_and_bad_content(tmp_path):
    target = tmp_path / "target"
    _write_root_key(target)
    link = tmp_path / "link"
    link.symlink_to(target)

    with pytest.raises(RootKeyLoadError, match="symbolic link"):
        load_root_key(link, version=1)
    with pytest.raises(RootKeyLoadError, match="unavailable"):
        load_root_key(tmp_path / "missing", version=1)
    with pytest.raises(RootKeyLoadError, match="absolute"):
        load_root_key("relative/key", version=1)

    bad_length = tmp_path / "bad-length"
    _write_root_key(bad_length, material=b"x" * 31)
    with pytest.raises(RootKeyLoadError, match="exactly 32 bytes"):
        load_root_key(bad_length, version=1)

    bad_lines = tmp_path / "bad-lines"
    bad_lines.write_bytes(base64.b64encode(ROOT_MATERIAL) + b"\n\n")
    bad_lines.chmod(0o400)
    with pytest.raises(RootKeyLoadError, match="content"):
        load_root_key(bad_lines, version=1)


def test_load_root_key_rejects_fingerprint_mismatch(tmp_path):
    key_path = tmp_path / "v1"
    _write_root_key(key_path)

    with pytest.raises(RootKeyLoadError, match="does not match"):
        load_root_key(key_path, version=1, expected_fingerprint_sha256="0" * 64)


def test_database_password_vectors_are_stable_and_purpose_separated(root_key):
    common = dict(
        root_key=root_key,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        account_username="tenant_11111111_g1",
        credential_generation=1,
        derivation_version=1,
    )

    dml = derive_tenant_dml_password(**common)
    platform_read = derive_platform_read_password(**common)

    # These vectors lock domain labels, UUID byte order, field order, length
    # prefixes, uint64 byte order, and unpadded Base64URL output.
    assert dml == "iUfpmWb8FQ3q_Br-v37YdE6o77onF8uTrVdKy90JGEI"
    assert platform_read == "PP5v0kR2J-OR2cOfFpja2gfYm7XAG9ih6twqIRp_nzc"
    assert dml != platform_read
    assert "=" not in dml and "=" not in platform_read
    assert len(base64.urlsafe_b64decode(dml + "=")) == 32
    assert len(base64.urlsafe_b64decode(platform_read + "=")) == 32


def test_database_password_binds_username_identity_and_versions(root_key):
    base = dict(
        root_key=root_key,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        account_username="tenant_11111111_g1",
        credential_generation=1,
        derivation_version=1,
    )
    expected = derive_tenant_dml_password(**base)

    variants = [
        {**base, "tenant_uuid": uuid.uuid4()},
        {**base, "database_uuid": uuid.uuid4()},
        {**base, "account_username": "tenant_11111111_g2"},
        {**base, "credential_generation": 2},
        {**base, "root_key": RootKey(version=8, material=ROOT_MATERIAL)},
    ]

    assert all(derive_tenant_dml_password(**variant) != expected for variant in variants)
    with pytest.raises(CryptoConfigurationError, match="unsupported"):
        derive_tenant_dml_password(**{**base, "derivation_version": 2})


def test_record_envelope_round_trip_and_random_nonce(root_key):
    plaintext = b"provider-secret-never-log"
    kwargs = dict(
        root_key=root_key,
        purpose="inventory-manager/test-record/v1",
        record_uuid=RECORD_UUID,
        revision=3,
        canonical_aad=_canonical_aad(),
        plaintext=plaintext,
    )

    first = encrypt_record(**kwargs)
    second = encrypt_record(**kwargs)

    assert len(first.nonce) == 12
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert plaintext not in first.ciphertext
    assert decrypt_record(
        root_key=root_key,
        envelope=first,
        purpose=kwargs["purpose"],
        record_uuid=RECORD_UUID,
        revision=3,
        canonical_aad=kwargs["canonical_aad"],
    ) == plaintext


def test_record_envelope_fixed_vector(root_key, monkeypatch):
    fixed_nonce = bytes.fromhex("000102030405060708090a0b")

    def nonce_source(size):
        assert size == 12
        return fixed_nonce

    monkeypatch.setattr(
        "inventory_control.crypto.envelope.secrets.token_bytes", nonce_source
    )
    envelope = encrypt_record(
        root_key=root_key,
        purpose="inventory-manager/test-record/v1",
        record_uuid=RECORD_UUID,
        revision=3,
        canonical_aad=_canonical_aad(),
        plaintext=b"provider-secret-never-log",
    )

    assert envelope.nonce == fixed_nonce
    assert envelope.ciphertext.hex() == (
        "49930d773f460e39cddab361c6d18f5734222af63ae21a6b53bb14e8cc3bb3ed"
        "128f368f0346f0dd73"
    )


@pytest.mark.parametrize("mutation", ["ciphertext", "nonce", "aad"])
def test_record_envelope_rejects_damage_without_plaintext_in_error(
    root_key, mutation
):
    plaintext = b"sensitive-value-that-must-not-appear"
    aad = _canonical_aad()
    envelope = encrypt_record(
        root_key=root_key,
        purpose="inventory-manager/test-record/v1",
        record_uuid=RECORD_UUID,
        revision=3,
        canonical_aad=aad,
        plaintext=plaintext,
    )
    if mutation == "ciphertext":
        changed = bytes([envelope.ciphertext[0] ^ 1]) + envelope.ciphertext[1:]
        envelope = replace(envelope, ciphertext=changed)
    elif mutation == "nonce":
        changed = bytes([envelope.nonce[0] ^ 1]) + envelope.nonce[1:]
        envelope = replace(envelope, nonce=changed)
    else:
        aad = aad + b"-changed"

    with pytest.raises(CryptoAuthenticationError) as caught:
        decrypt_record(
            root_key=root_key,
            envelope=envelope,
            purpose="inventory-manager/test-record/v1",
            record_uuid=RECORD_UUID,
            revision=3,
            canonical_aad=aad,
        )
    assert plaintext.decode() not in str(caught.value)


@pytest.mark.parametrize(
    "change", ["purpose", "record", "revision", "root", "material", "aad"]
)
def test_record_envelope_rejects_context_swaps(root_key, change):
    envelope = encrypt_record(
        root_key=root_key,
        purpose="inventory-manager/test-record/v1",
        record_uuid=RECORD_UUID,
        revision=3,
        canonical_aad=_canonical_aad(),
        plaintext=b"secret",
    )
    decrypt_kwargs = dict(
        root_key=root_key,
        envelope=envelope,
        purpose="inventory-manager/test-record/v1",
        record_uuid=RECORD_UUID,
        revision=3,
        canonical_aad=_canonical_aad(),
    )
    if change == "purpose":
        decrypt_kwargs["purpose"] = "inventory-manager/another-record/v1"
    elif change == "record":
        decrypt_kwargs["record_uuid"] = uuid.uuid4()
    elif change == "revision":
        decrypt_kwargs["revision"] = 4
    elif change == "root":
        decrypt_kwargs["root_key"] = RootKey(version=8, material=ROOT_MATERIAL)
    elif change == "material":
        decrypt_kwargs["root_key"] = RootKey(
            version=7, material=bytes(reversed(ROOT_MATERIAL))
        )
    else:
        decrypt_kwargs["canonical_aad"] = _canonical_aad(revision=4)

    with pytest.raises(CryptoAuthenticationError):
        decrypt_record(**decrypt_kwargs)


def test_record_envelope_rejects_unsupported_versions_and_noncanonical_aad(root_key):
    common = dict(
        root_key=root_key,
        purpose="inventory-manager/test-record/v1",
        record_uuid=RECORD_UUID,
        revision=1,
        canonical_aad=b"canonical",
        plaintext=b"secret",
    )
    with pytest.raises(CryptoConfigurationError, match="unsupported"):
        encrypt_record(**{**common, "crypto_version": 2})
    with pytest.raises(CryptoConfigurationError, match="unsupported"):
        encrypt_record(**{**common, "aad_version": 2})
    with pytest.raises(CryptoConfigurationError, match="canonical AAD"):
        encrypt_record(**{**common, "canonical_aad": b""})


def test_envelope_metadata_has_expected_persistable_shape(root_key):
    envelope = encrypt_record(
        root_key=root_key,
        purpose="inventory-manager/test-record/v1",
        record_uuid=RECORD_UUID,
        revision=1,
        canonical_aad=b"canonical",
        plaintext=b"secret",
    )

    assert isinstance(envelope, EncryptedEnvelope)
    assert envelope.root_key_version == 7
    assert envelope.crypto_version == 1
    assert envelope.aad_version == 1
    assert len(envelope.ciphertext) == len(b"secret") + 16
    assert "ciphertext" not in repr(envelope)
    assert "nonce" not in repr(envelope)
