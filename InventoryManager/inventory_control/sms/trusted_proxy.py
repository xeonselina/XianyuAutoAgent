"""Explicit trusted-proxy source resolution for SMS rate-limit buckets."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Iterable

from flask import Request

from .contracts import TrustedSourceBucket


@dataclass(frozen=True, slots=True, repr=False)
class TrustedProxySourcePolicy:
    """Deployment-owned proxy trust; there is intentionally no default."""

    trusted_proxy_networks: tuple[
        ipaddress.IPv4Network | ipaddress.IPv6Network, ...
    ]
    max_forwarded_addresses: int

    @classmethod
    def from_cidrs(
        cls,
        cidrs: Iterable[str],
        *,
        max_forwarded_addresses: int,
    ) -> "TrustedProxySourcePolicy":
        if isinstance(cidrs, (str, bytes)):
            raise TypeError("trusted proxy CIDRs must be an iterable")
        try:
            raw_values = tuple(cidrs)
        except TypeError:
            raise TypeError("trusted proxy CIDRs must be an iterable") from None
        if not raw_values:
            raise ValueError("at least one trusted proxy CIDR is required")
        if (
            isinstance(max_forwarded_addresses, bool)
            or not isinstance(max_forwarded_addresses, int)
            or not 1 <= max_forwarded_addresses <= 16
        ):
            raise ValueError("max forwarded addresses must be between 1 and 16")
        networks = []
        for raw in raw_values:
            if not isinstance(raw, str) or raw != raw.strip() or not raw:
                raise ValueError("trusted proxy CIDR is invalid")
            try:
                network = ipaddress.ip_network(raw, strict=True)
            except ValueError:
                raise ValueError("trusted proxy CIDR is invalid") from None
            if network in networks:
                raise ValueError("trusted proxy CIDRs must be unique")
            networks.append(network)
        return cls(
            trusted_proxy_networks=tuple(networks),
            max_forwarded_addresses=max_forwarded_addresses,
        )

    def __post_init__(self) -> None:
        if (
            not self.trusted_proxy_networks
            or any(
                not isinstance(
                    network,
                    (ipaddress.IPv4Network, ipaddress.IPv6Network),
                )
                for network in self.trusted_proxy_networks
            )
            or isinstance(self.max_forwarded_addresses, bool)
            or not isinstance(self.max_forwarded_addresses, int)
            or not 1 <= self.max_forwarded_addresses <= 16
        ):
            raise ValueError("trusted proxy source policy is invalid")

    def __repr__(self) -> str:
        return (
            "TrustedProxySourcePolicy("
            f"network_count={len(self.trusted_proxy_networks)}, "
            f"max_forwarded_addresses={self.max_forwarded_addresses})"
        )


class TrustedProxySourceResolver:
    """Resolve one canonical client bucket without trusting browser headers."""

    __slots__ = ("_policy",)

    def __init__(self, policy: TrustedProxySourcePolicy) -> None:
        if not isinstance(policy, TrustedProxySourcePolicy):
            raise TypeError("policy must be a TrustedProxySourcePolicy")
        self._policy = policy

    def __call__(self, request: Request) -> TrustedSourceBucket:
        if not isinstance(request, Request):
            raise TypeError("request must be a Flask Request")
        peer = _parse_ip(request.remote_addr)
        if peer is None:
            return TrustedSourceBucket.unknown()
        if not self._is_trusted_proxy(peer):
            return TrustedSourceBucket.from_trusted_ip(peer.compressed)

        header_values = request.headers.getlist("X-Forwarded-For")
        if len(header_values) != 1:
            return TrustedSourceBucket.unknown()
        raw_header = header_values[0]
        if (
            not isinstance(raw_header, str)
            or not raw_header
            or len(raw_header) > 1024
            or any(ord(character) < 32 for character in raw_header)
        ):
            return TrustedSourceBucket.unknown()
        raw_addresses = tuple(part.strip() for part in raw_header.split(","))
        if (
            not raw_addresses
            or len(raw_addresses) > self._policy.max_forwarded_addresses
            or any(not value for value in raw_addresses)
        ):
            return TrustedSourceBucket.unknown()
        forwarded = tuple(_parse_ip(value) for value in raw_addresses)
        if any(value is None for value in forwarded):
            return TrustedSourceBucket.unknown()

        # The trusted peer appended the actual source at the right edge. Walk
        # backwards over only explicitly trusted proxies; the first remaining
        # address is the rate-limit source. If every address is a trusted
        # proxy, the leftmost address remains the least-derived source fact.
        chain = tuple(forwarded) + (peer,)
        index = len(chain) - 2
        while index > 0 and self._is_trusted_proxy(chain[index]):
            index -= 1
        source = chain[index]
        return TrustedSourceBucket.from_trusted_ip(source.compressed)

    def _is_trusted_proxy(
        self,
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> bool:
        return any(
            address.version == network.version and address in network
            for network in self._policy.trusted_proxy_networks
        )

    def __repr__(self) -> str:
        return "TrustedProxySourceResolver(<explicit-policy>)"


def _parse_ip(
    value: object,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


__all__ = [
    "TrustedProxySourcePolicy",
    "TrustedProxySourceResolver",
]
