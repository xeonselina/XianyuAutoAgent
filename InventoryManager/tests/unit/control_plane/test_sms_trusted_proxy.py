from __future__ import annotations

import pytest
from flask import Flask, request

from inventory_control.sms import (
    TrustedProxySourcePolicy,
    TrustedProxySourceResolver,
)


def _resolver():
    return TrustedProxySourceResolver(
        TrustedProxySourcePolicy.from_cidrs(
            ["10.0.0.0/8", "2001:db8:100::/48"],
            max_forwarded_addresses=4,
        )
    )


def _resolve(*, remote_addr: str, headers=None):
    app = Flask(__name__)
    with app.test_request_context(
        "/",
        environ_base={"REMOTE_ADDR": remote_addr},
        headers=headers or {},
    ):
        return _resolver()(request)


def test_untrusted_direct_peer_cannot_spoof_forwarded_header() -> None:
    resolved = _resolve(
        remote_addr="203.0.113.9",
        headers={"X-Forwarded-For": "198.51.100.10"},
    )

    assert resolved.value == "ip4:203.0.113.9"


def test_trusted_proxy_chain_selects_first_untrusted_from_right() -> None:
    resolved = _resolve(
        remote_addr="10.0.0.5",
        headers={
            "X-Forwarded-For": "192.0.2.10, 198.51.100.20, 10.1.0.8"
        },
    )

    assert resolved.value == "ip4:198.51.100.20"


def test_trusted_ipv6_proxy_returns_compressed_ipv6_source() -> None:
    resolved = _resolve(
        remote_addr="2001:db8:100::5",
        headers={"X-Forwarded-For": "2001:db8:200:0:0:0:0:10"},
    )

    assert resolved.value == "ip6:2001:db8:200::10"


@pytest.mark.parametrize(
    "header",
    [
        "not-an-ip",
        "198.51.100.1,,10.0.0.8",
        "198.51.100.1, 1.1.1.1, 2.2.2.2, 3.3.3.3, 10.0.0.8",
    ],
)
def test_invalid_or_oversized_trusted_chain_uses_unknown_bucket(header) -> None:
    resolved = _resolve(
        remote_addr="10.0.0.5",
        headers={"X-Forwarded-For": header},
    )

    assert resolved.value == "unknown"


def test_missing_forwarded_header_on_trusted_peer_is_conservative() -> None:
    assert _resolve(remote_addr="10.0.0.5").value == "unknown"


@pytest.mark.parametrize(
    "cidrs,max_addresses",
    [
        ([], 2),
        (["10.0.0.1/8"], 2),
        (["10.0.0.0/8", "10.0.0.0/8"], 2),
        (["10.0.0.0/8"], 0),
        (["10.0.0.0/8"], 17),
    ],
)
def test_policy_has_no_implicit_or_ambiguous_trust(cidrs, max_addresses) -> None:
    with pytest.raises(ValueError):
        TrustedProxySourcePolicy.from_cidrs(
            cidrs,
            max_forwarded_addresses=max_addresses,
        )
