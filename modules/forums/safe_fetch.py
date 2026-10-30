"""
Guard for outbound HTTP requests whose URL comes from OUTSIDE the framework.

Why this exists
---------------
Without a guard, a tool like `module-image` accepts any `image_url` and
fetches it with no host or IP check. From an ordinary user account — no admin
rights needed — that reaches `license:9000`, `keycloak:8080` and
`updater:9999` (the container holding the Docker socket), and the error text
tells the caller *which*: "content-type: application/json" for a live service,
`ConnectTimeout` for a closed port, `ConnectError` for an unreachable net.
That is an internal-network scanner with a readable oracle. On a cloud VPS
the same path reaches `169.254.169.254`, where metadata typically hands out
IAM credentials.

What this does NOT do
---------------------
**No host allowlist.** An allowlist is right for a dashboard that proxies a
fixed set of APIs; it is wrong here. Our modules exist to fetch arbitrary
investigation targets — a list of permitted hosts would either be useless or
would silently cut coverage.

Honest limit
------------
This resolves the hostname, rejects the request if ANY resolved address is
private, and re-validates on every redirect hop. Between that resolution and
the socket connect, a DNS record with a very low TTL can still flip to a
private address (classic DNS rebinding). Closing that hole needs connect-time
pinning inside the transport; it is not done here and is stated rather than
implied. The window is small and the pre-flight check plus per-hop
re-validation removes the entire trivial attack.

The Tor path is deliberately exempt: `.onion` names do not resolve through
the system resolver and the private-address model does not apply to them.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# Networks no investigation target ever legitimately lives on. The stdlib
# classifiers cover most of it; the explicit list catches ranges older
# Pythons miss and documents intent.
_EXTRA_BLOCKED = [
    ipaddress.ip_network("100.64.0.0/10"),   # CGNAT (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),    # IETF protocol assignments
    ipaddress.ip_network("198.18.0.0/15"),   # benchmarking (RFC 2544)
    ipaddress.ip_network("64:ff9b::/96"),    # NAT64
]

MAX_REDIRECTS = 3


class BlockedURL(Exception):
    """The URL was refused before any request went out."""


def _ip_is_blocked(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True                     # unparseable → fail closed
    # `::ffff:127.0.0.1` must be judged as 127.0.0.1, not as "some IPv6".
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped:
        ip = mapped
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        return True
    return any(ip in net for net in _EXTRA_BLOCKED)


def is_onion(host: str) -> bool:
    return host.lower().endswith(".onion")


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [i[4][0] for i in infos]


async def assert_public_url(url: str, *, allow_http: bool = True) -> None:
    """Raise BlockedURL unless `url` points at a public host.

    `allow_http` is True because plenty of legitimate OSINT targets — paste
    sites, small forums, archived pages — are still plain HTTP. Refusing them
    would cut real coverage to buy nothing: the risk here is the destination
    address, not the scheme.
    """
    parsed = urlparse(url)
    if parsed.scheme not in (("http", "https") if allow_http else ("https",)):
        raise BlockedURL(f"unsupported scheme: {parsed.scheme or '(none)'}")
    host = parsed.hostname or ""
    if not host:
        raise BlockedURL("no host in URL")
    if is_onion(host):
        return                          # Tor path — see module docstring
    # A literal IP skips DNS entirely and is checked directly.
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        try:
            addrs = await _resolve(host)
        except Exception as e:          # noqa: BLE001
            raise BlockedURL(f"cannot resolve {host}: {type(e).__name__}") from e
    if not addrs:
        raise BlockedURL(f"cannot resolve {host}")
    # ALL addresses must be public: a host that resolves to one public and one
    # private address would otherwise be usable by retrying until the private
    # one is picked.
    for a in addrs:
        if _ip_is_blocked(a):
            raise BlockedURL(f"{host} resolves to a non-public address ({a})")


async def safe_request(
    client: httpx.AsyncClient, method: str, url: str, **kw
) -> httpx.Response:
    """Perform a request, validating the target — and every redirect hop.

    Redirects are followed manually: `follow_redirects=True` would let a
    public host bounce the request to `http://169.254.169.254/` with nothing
    checking the new target.
    """
    kw.pop("follow_redirects", None)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        await assert_public_url(current)
        resp = await client.request(method, current, follow_redirects=False, **kw)
        if resp.status_code not in (301, 302, 303, 307, 308):
            return resp
        location = resp.headers.get("location")
        if not location:
            return resp
        current = str(httpx.URL(current).join(location))
    raise BlockedURL(f"too many redirects (>{MAX_REDIRECTS})")


async def safe_get(client: httpx.AsyncClient, url: str, **kw) -> httpx.Response:
    return await safe_request(client, "GET", url, **kw)
