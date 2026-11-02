"""Request rate limiting keyed by the real client IP or authenticated user."""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache

from slowapi import Limiter
from starlette.requests import Request

# Uvicorn reads the same variable for --forwarded-allow-ips, so the app and the
# server trust exactly the same proxies by default.
FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"
DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1,::1"
RATE_LIMIT_IDENTITY_ATTR = "rate_limit_identity"

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _parse_trusted_proxies(raw: str) -> tuple[bool, tuple[_Network, ...]]:
    """Return (trust_all, networks) for a comma-separated IP/CIDR list."""
    networks: list[_Network] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        if item == "*":
            return True, ()
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue  # Unix socket paths and hostnames cannot match a peer IP.
    return False, tuple(networks)


def _is_trusted_proxy(host: str, trusted: tuple[bool, tuple[_Network, ...]]) -> bool:
    trust_all, networks = trusted
    if trust_all:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in networks)


def client_ip(request: Request, trusted_proxies: str | None = None) -> str:
    """Return the real client IP, honouring X-Forwarded-For only from trusted peers.

    The forwarded chain is walked from the right (closest proxy) and the first
    untrusted address wins, so a client cannot spoof its address by sending
    its own X-Forwarded-For through a proxy that appends to the header.
    """
    raw = trusted_proxies
    if raw is None:
        raw = os.environ.get(FORWARDED_ALLOW_IPS_ENV, DEFAULT_FORWARDED_ALLOW_IPS)
    trusted = _parse_trusted_proxies(raw)
    client = getattr(request, "client", None)
    peer = client.host if client else ""
    if not peer or not _is_trusted_proxy(peer, trusted):
        return peer or "unknown"
    forwarded = getattr(request, "headers", {}).get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _is_trusted_proxy(hop, trusted):
            return hop
    return hops[0] if hops else peer


def bind_rate_limit_identity(request: Request, user_id: str) -> None:
    """Key this request's rate limits by account instead of client address."""
    setattr(request.state, RATE_LIMIT_IDENTITY_ATTR, f"user:{user_id}")


def rate_limit_key(request: Request) -> str:
    """Return the per-user key when authentication bound one, else the client IP."""
    identity = getattr(request.state, RATE_LIMIT_IDENTITY_ATTR, None)
    if isinstance(identity, str) and identity:
        return identity
    return f"ip:{client_ip(request)}"


limiter = Limiter(key_func=rate_limit_key)
