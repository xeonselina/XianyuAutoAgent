from __future__ import annotations

import json
import os

import pytest

from inventory_control.operations import (
    HostRecoveryMarkerLoadError,
    HostRecoveryMarkerMode,
    MAX_MARKER_BYTES,
    load_host_recovery_marker,
)


INSTALLATION = "1" * 64
MARKER = "2" * 64


def _payload(**changes):
    selected = {
        "format_version": 1,
        "mode": "normal",
        "installation_fingerprint": INSTALLATION,
        "marker_fingerprint": MARKER,
    }
    selected.update(changes)
    return selected


def _write(path, value, *, mode=0o400):
    encoded = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.write_bytes(encoded)
    path.chmod(mode)
    return path


def _load(path):
    return load_host_recovery_marker(path, expected_owner_uid=os.getuid())


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("normal", HostRecoveryMarkerMode.NORMAL),
        ("host_restore", HostRecoveryMarkerMode.HOST_RESTORE),
    ],
)
def test_loader_accepts_only_the_fixed_v1_marker_shape(tmp_path, mode, expected):
    path = _write(tmp_path / "deployment-marker.json", _payload(mode=mode))
    marker = _load(path)
    assert marker.mode is expected
    assert marker.installation_fingerprint == INSTALLATION
    assert marker.marker_fingerprint == MARKER


@pytest.mark.parametrize(
    "payload",
    [
        {**_payload(), "extra": "not-allowed"},
        {key: value for key, value in _payload().items() if key != "mode"},
        _payload(format_version=2),
        _payload(format_version=True),
        _payload(format_version=1.0),
        _payload(mode="recovery-ish"),
        _payload(installation_fingerprint="not-a-fingerprint"),
        _payload(marker_fingerprint="A" * 64),
        [],
    ],
)
def test_unknown_missing_or_invalid_marker_data_is_rejected(tmp_path, payload):
    path = _write(tmp_path / "deployment-marker.json", payload)
    with pytest.raises(HostRecoveryMarkerLoadError) as captured:
        _load(path)
    assert str(captured.value) == "deployment marker is unavailable"
    assert str(path) not in str(captured.value)


def test_duplicate_json_keys_and_invalid_utf8_are_rejected(tmp_path):
    duplicate = (
        b'{"format_version":1,"format_version":1,"mode":"normal",'
        b'"installation_fingerprint":"'
        + INSTALLATION.encode()
        + b'","marker_fingerprint":"'
        + MARKER.encode()
        + b'"}'
    )
    for index, encoded in enumerate((duplicate, b"\xff\xfe")):
        path = _write(tmp_path / f"marker-{index}", encoded)
        with pytest.raises(HostRecoveryMarkerLoadError):
            _load(path)


def test_loader_rejects_symlink_directory_and_writable_file(tmp_path):
    target = _write(tmp_path / "target", _payload())
    symlink = tmp_path / "marker-link"
    symlink.symlink_to(target)
    directory = tmp_path / "marker-directory"
    directory.mkdir()
    writable = _write(tmp_path / "marker-writable", _payload(), mode=0o620)

    for path in (symlink, directory, writable):
        with pytest.raises(HostRecoveryMarkerLoadError):
            _load(path)


def test_loader_rejects_wrong_owner_oversize_relative_and_missing(tmp_path):
    valid = _write(tmp_path / "valid", _payload())
    with pytest.raises(HostRecoveryMarkerLoadError):
        load_host_recovery_marker(
            valid,
            expected_owner_uid=os.getuid() + 1,
        )

    oversized = _write(tmp_path / "oversized", b"x" * (MAX_MARKER_BYTES + 1))
    for path in (oversized, "relative-marker", tmp_path / "missing"):
        with pytest.raises(HostRecoveryMarkerLoadError):
            _load(path)


@pytest.mark.parametrize("owner", [-1, True, "0"])
def test_expected_owner_uid_must_be_a_nonnegative_integer(tmp_path, owner):
    path = _write(tmp_path / "valid", _payload())
    with pytest.raises(ValueError, match="expected_owner_uid"):
        load_host_recovery_marker(path, expected_owner_uid=owner)
