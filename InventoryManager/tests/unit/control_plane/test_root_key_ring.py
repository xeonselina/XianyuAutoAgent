from __future__ import annotations

import base64
from pathlib import Path

import pytest

from inventory_control.crypto import (
    RootKeyLifecycle,
    RootKeyLoadError,
    RootKeyVersionFact,
    load_root_key_ring,
)


KEY_V1 = bytes(range(32))
KEY_V2 = bytes(range(1, 33))
KEY_V3 = b"r" * 32


def _write_key(directory: Path, version: int, material: bytes) -> Path:
    path = directory / f"v{version}"
    path.write_bytes(base64.b64encode(material) + b"\n")
    path.chmod(0o400)
    return path


def _fact(
    version: int,
    material: bytes,
    status: RootKeyLifecycle,
) -> RootKeyVersionFact:
    import hashlib

    return RootKeyVersionFact(
        version=version,
        fingerprint_sha256=hashlib.sha256(material).hexdigest(),
        status=status,
    )


def test_registry_selects_one_active_and_resolves_legacy_for_existing_records(
    tmp_path,
):
    _write_key(tmp_path, 1, KEY_V1)
    _write_key(tmp_path, 2, KEY_V2)

    ring = load_root_key_ring(
        tmp_path,
        registry=(
            _fact(1, KEY_V1, RootKeyLifecycle.LEGACY),
            _fact(2, KEY_V2, RootKeyLifecycle.ACTIVE),
            _fact(3, KEY_V3, RootKeyLifecycle.RETIRED),
        ),
    )

    assert ring.active_version == 2
    assert ring.active_key.version == 2
    assert ring.key_for_existing_reference(1).version == 1
    assert ring.loaded_versions == (1, 2)
    with pytest.raises(RootKeyLoadError, match="unavailable"):
        ring.key_for_existing_reference(3)
    with pytest.raises(RootKeyLoadError, match="unavailable"):
        ring.key_for_existing_reference(999)
    assert base64.b64encode(KEY_V1).decode("ascii") not in repr(ring)
    assert "<redacted>" in repr(ring)


@pytest.mark.parametrize(
    "registry",
    [
        (),
        (
            _fact(1, KEY_V1, RootKeyLifecycle.LEGACY),
            _fact(2, KEY_V2, RootKeyLifecycle.LEGACY),
        ),
        (
            _fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),
            _fact(2, KEY_V2, RootKeyLifecycle.ACTIVE),
        ),
    ],
)
def test_registry_requires_exactly_one_active_version(tmp_path, registry):
    for fact in registry:
        _write_key(
            tmp_path,
            fact.version,
            KEY_V1 if fact.version == 1 else KEY_V2,
        )
    with pytest.raises(RootKeyLoadError):
        load_root_key_ring(tmp_path, registry=registry)


def test_mounted_files_must_exactly_match_active_and_legacy_registry(tmp_path):
    registry = (_fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),)
    with pytest.raises(RootKeyLoadError, match="do not match"):
        load_root_key_ring(tmp_path, registry=registry)

    _write_key(tmp_path, 1, KEY_V1)
    _write_key(tmp_path, 2, KEY_V2)
    with pytest.raises(RootKeyLoadError, match="do not match"):
        load_root_key_ring(tmp_path, registry=registry)


def test_retired_key_must_not_be_mounted(tmp_path):
    _write_key(tmp_path, 1, KEY_V1)
    _write_key(tmp_path, 3, KEY_V3)
    with pytest.raises(RootKeyLoadError, match="do not match"):
        load_root_key_ring(
            tmp_path,
            registry=(
                _fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),
                _fact(3, KEY_V3, RootKeyLifecycle.RETIRED),
            ),
        )


def test_fingerprint_mismatch_and_unknown_directory_entry_fail_closed(tmp_path):
    _write_key(tmp_path, 1, KEY_V1)
    with pytest.raises(RootKeyLoadError, match="fingerprint"):
        load_root_key_ring(
            tmp_path,
            registry=(_fact(1, KEY_V2, RootKeyLifecycle.ACTIVE),),
        )

    (tmp_path / "README").write_text("not a key", encoding="utf-8")
    with pytest.raises(RootKeyLoadError, match="invalid entry"):
        load_root_key_ring(
            tmp_path,
            registry=(_fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),),
        )


def test_symlink_key_and_relative_directory_are_rejected(tmp_path):
    target = _write_key(tmp_path, 1, KEY_V1)
    target.rename(tmp_path / "material")
    (tmp_path / "v1").symlink_to(tmp_path / "material")
    with pytest.raises(RootKeyLoadError, match="invalid entry"):
        load_root_key_ring(
            tmp_path,
            registry=(_fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),),
        )

    with pytest.raises(RootKeyLoadError, match="absolute"):
        load_root_key_ring(
            "relative/root-keys",
            registry=(_fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),),
        )


def test_duplicate_registry_version_or_fingerprint_is_rejected(tmp_path):
    _write_key(tmp_path, 1, KEY_V1)
    duplicate_version = (
        _fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),
        _fact(1, KEY_V2, RootKeyLifecycle.LEGACY),
    )
    with pytest.raises(RootKeyLoadError, match="duplicate"):
        load_root_key_ring(tmp_path, registry=duplicate_version)

    duplicate_fingerprint = (
        _fact(1, KEY_V1, RootKeyLifecycle.ACTIVE),
        RootKeyVersionFact(
            version=2,
            fingerprint_sha256=_fact(
                1, KEY_V1, RootKeyLifecycle.ACTIVE
            ).fingerprint_sha256,
            status=RootKeyLifecycle.LEGACY,
        ),
    )
    with pytest.raises(RootKeyLoadError, match="duplicate"):
        load_root_key_ring(tmp_path, registry=duplicate_fingerprint)
