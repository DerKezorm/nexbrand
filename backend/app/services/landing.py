"""The page a sign-in through a provider started from: a direct link survives the trip to the provider.

The shared sign-in module carries what the protocol needs in its attempt cookie; where nexbrand lands afterwards is
nexbrand's own business. The page travels in a cookie of its own beside the attempt, signed with a key derived from
the server secret, and is checked with ``safe_next`` going in and coming back: only a page of nexbrand's own, never
another host, never the API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import posixpath
import re
from urllib.parse import unquote

from ..config import get_settings

#: The cookie beside the attempt cookie, as long-lived as the attempt.
COOKIE = "nexbrand_oidc_next" + get_settings().cookie_name_suffix()
MINUTES = 10

#: A page of nexbrand's own to land on after the provider: a path on this server with its query. Never another
#: host (``//host``, ``/\host``, a scheme), never the API, nothing but printable characters without spaces.
_NEXT = re.compile(r"/(?![/\\])[A-Za-z0-9\-._~!$&'()*+,;=:@%/?]{0,499}")


def safe_next(value: object) -> str | None:
    """The page to land on after signing in, or None if ``value`` is not one of nexbrand's own (no open redirect)."""
    if not isinstance(value, str) or not _NEXT.fullmatch(value) or value == "/":
        return None
    # Compared as the server and a browser read the path: decoded (also twice), dots resolved, any case.
    path = value.split("?", 1)[0]
    for _ in range(3):
        path = unquote(path)
    if path.startswith(("//", "/\\")) or "\\" in path:
        return None
    path = posixpath.normpath(path).lower()
    if path == "/api" or path.startswith("/api/"):
        return None
    return value


def _key() -> bytes:
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexbrand-oidc-next:" + secret).digest()


def _signature(page: str) -> str:
    digest = hmac.new(_key(), page.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def pack(page: str | None) -> str | None:
    """The cookie value for a page (the page in base64, a dot, its signature: nothing a cookie has to quote), or None
    when it is not one to land on."""
    landing = safe_next(page)
    if not landing:
        return None
    encoded = base64.urlsafe_b64encode(landing.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded}.{_signature(landing)}"


def read(value: str | None) -> str | None:
    """The page from the cookie: signed by this server and still one of nexbrand's own, else None."""
    if not value or value.count(".") != 1:
        return None
    encoded, signature = value.split(".")
    try:
        page = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(signature.encode(), _signature(page).encode()):
        return None
    return safe_next(page)
