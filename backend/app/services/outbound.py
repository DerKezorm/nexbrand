"""Asking addresses outside on someone's behalf: a page, a style sheet, a file of a repository, a logo.

**Closed until the operator opens it** (``collect_allowed``): whoever runs the page learns that someone at this
server asked for it.

A server asking addresses it is handed must never be turned against its own network (as in nexlore's link titles):
only ``http`` and ``https``, the name is resolved here and every address it gives must be public (no loopback,
private, link-local, shared, reserved or multicast one), and the connection goes to exactly the address checked (the
name stays in the ``Host`` header and in TLS, so the certificate is still checked for it). Redirects are followed by
hand, each checked again. Every answer is read up to a limit; the log names the host, never the whole address.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger("nexbrand.outbound")

TIMEOUT = 12.0
MAX_REDIRECTS = 4
MAX_URL = 2000
AGENT = "nexbrand (collecting a brand's colours)"
#: Headers that only the first host gets, never one a redirect leads to.
PRIVATE_HEADERS = {"authorization", "cookie", "proxy-authorization"}


class FetchError(ValueError):
    """Why nothing came: the address, the network, or the answer."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


Resolver = Callable[[str, int], list[str]]


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise FetchError("not_found") from exc
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


#: The tests put their own in.
resolver: Resolver = _resolve
transport: httpx.BaseTransport | None = None


def public(address: str) -> bool:
    """Whether an address lies outside every own, shared or special network."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    special = ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_private
    return ip.is_global and not special


def _checked(url: str) -> tuple[str, str, int, str]:
    if len(url) > MAX_URL:
        raise FetchError("bad_address")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise FetchError("bad_address")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise FetchError("bad_address") from exc
    host = parts.hostname
    addresses = resolver(host, port)
    if not addresses or not all(public(address) for address in addresses):
        raise FetchError("not_public")
    return parts.scheme, host, port, addresses[0]


@dataclass
class Fetched:
    url: str
    content_type: str
    body: bytes


def get(url: str, *, limit: int, accept: str = "*/*", headers: dict[str, str] | None = None) -> Fetched:
    """One address, its redirects followed by hand and checked each; at most ``limit`` bytes (more is an error)."""
    deadline = time.monotonic() + TIMEOUT
    origin: tuple[str, str, int] | None = None
    given = dict(headers or {})
    with httpx.Client(transport=transport, follow_redirects=False, trust_env=False) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            scheme, host, port, ip = _checked(url)
            origin = origin or (scheme, host.lower(), port)
            parts = urlsplit(url)
            target = f"[{ip}]" if ":" in ip else ip
            direct = parts._replace(netloc=f"{target}:{port}").geturl()
            left = deadline - time.monotonic()
            if left <= 0:
                raise FetchError("timeout")
            named = host if port in (80, 443) else f"{host}:{port}"
            if (scheme, host.lower(), port) != origin:
                # A key is for the host it was given for: a redirect elsewhere goes without it from there on,
                # as browsers and the usual clients do.
                given = {key: value for key, value in given.items() if key.lower() not in PRIVATE_HEADERS}
            sent = {"Host": named, "User-Agent": AGENT, "Accept": accept, **given}
            extensions = {"sni_hostname": host} if scheme == "https" else {}
            try:
                with client.stream("GET", direct, headers=sent, timeout=left, extensions=extensions) as answer:
                    if answer.status_code in (301, 302, 303, 307, 308):
                        location = answer.headers.get("location")
                        if not location:
                            raise FetchError("no_answer")
                        url = urljoin(url, location)
                        continue
                    if answer.status_code == 404:
                        raise FetchError("not_found")
                    if answer.status_code in (401, 403):
                        raise FetchError("refused")
                    if answer.status_code != 200:
                        raise FetchError("no_answer")
                    declared = answer.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > limit:
                        raise FetchError("too_large")
                    body = b""
                    for chunk in answer.iter_bytes():
                        body += chunk
                        if len(body) > limit:
                            raise FetchError("too_large")
                        if time.monotonic() > deadline:
                            raise FetchError("timeout")
                    return Fetched(url=url, content_type=answer.headers.get("content-type", ""), body=body)
            except httpx.TimeoutException as exc:
                raise FetchError("timeout") from exc
            except httpx.HTTPError as exc:
                logger.info("Not reached host=%s error=%s", host, type(exc).__name__)
                raise FetchError("unreachable") from exc
    raise FetchError("too_many_redirects")
