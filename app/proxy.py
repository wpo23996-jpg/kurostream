"""Media proxy: rewrites HLS playlists to same-origin URLs and forwards bytes.

This is what makes a third-party m3u8 playable in a plain <video> tag:
  * Referer / UA are injected server-side (hotlink protection)
  * relative segment URIs are resolved and rewritten
  * CORS is same-origin, no browser preflight issues
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import re
from urllib.parse import urljoin, urlparse

from .config import PUBLIC_BASE, settings
from .providers import all_hosts

log = logging.getLogger("kurostream.proxy")

URI_ATTR = re.compile(r'URI="([^"]+)"')

_ALLOWED: set[str] = set(settings.allowed_media_hosts) | set(all_hosts())


def b64e(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode().rstrip("=")


def b64d(value: str) -> str:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad).decode("utf-8", "replace")


def host_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return False
    except ValueError:
        pass
    return any(host == h or host.endswith("." + h) for h in _ALLOWED)


def proxy_url(url: str, referer: str = "") -> str:
    ref = b64e(referer) if referer else ""
    path = urlparse(url).path.lower()
    endpoint = "hls" if path.endswith(".m3u8") else "raw"
    # KS_PUBLIC_BASE makes the URL absolute so native shells (capacitor://localhost)
    # can resolve it; browsers on the same origin get the same valid URL.
    return f"{PUBLIC_BASE}/api/media/{endpoint}?u={b64e(url)}&r={ref}"


def rewrite_hls(text: str, base_url: str, referer: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append(raw)
            continue
        if line.startswith("#"):
            def _fix(match: re.Match) -> str:
                return f'URI="{proxy_url(urljoin(base_url, match.group(1)), referer)}"'

            lines.append(URI_ATTR.sub(_fix, raw))
        else:
            lines.append(proxy_url(urljoin(base_url, line), referer))
    return "\n".join(lines) + "\n"
