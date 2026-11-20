"""Shared HTTP layer: thread-safe curl_cffi session with retry + rate limit."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from curl_cffi import requests as cr

from .cf import solver
from .config import settings

log = logging.getLogger("kurostream.http")

CF_MARKERS = ("Just a moment", "_cf_chl_opt", "cdn-cgi/challenge-platform", "Enable JavaScript and cookies")


@dataclass
class Response:
    status: int
    url: str
    text: str
    content: bytes
    headers: dict[str, str]

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = max(0.0, interval)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


class Http:
    """One instance per provider; safe to call from several threads."""

    def __init__(
        self,
        base: str = "",
        *,
        impersonate: str | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        min_interval: float | None = None,
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base = base.rstrip("/")
        self.timeout = settings.timeout if timeout is None else timeout
        self.retries = settings.retries if retries is None else retries
        self.proxy = settings.proxy if proxy is None else proxy
        self.limiter = RateLimiter(settings.min_interval if min_interval is None else min_interval)
        self._lock = threading.Lock()
        self.session = cr.Session(impersonate=impersonate or settings.impersonate)
        self.default_headers = {
            "User-Agent": settings.user_agent,
            "Accept-Language": settings.accept_language,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if headers:
            self.default_headers.update(headers)
        self.session.headers.update(self.default_headers)

    # ------------------------------------------------------------------ request
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        referer: str | None = None,
        binary: bool = False,
        allow_redirects: bool = True,
        retries: int | None = None,
        timeout: float | None = None,
    ) -> Response:
        full = url if url.startswith("http") else f"{self.base}/{url.lstrip('/')}"
        attempts = self.retries if retries is None else retries
        last: Exception | None = None
        flare_cookies: dict[str, str] = {}
        flare_ua: str = ""
        flare_retried: bool = False

        for attempt in range(attempts):
            self.limiter.wait()
            hdrs = dict(self.default_headers)
            if referer:
                hdrs["Referer"] = referer
            if flare_ua:
                hdrs["User-Agent"] = flare_ua
            if flare_cookies:
                hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in flare_cookies.items())
            if headers:
                hdrs.update(headers)
            try:
                with self._lock:
                    resp = self.session.get(
                        full,
                        headers=hdrs,
                        params=params,
                        timeout=self.timeout if timeout is None else timeout,
                        proxy=self.proxy,
                        allow_redirects=allow_redirects,
                    )
                text = "" if binary else resp.text
                body = resp.content if binary else b""
                if resp.status_code in (403, 429, 503) or any(m in text[:4000] for m in CF_MARKERS):
                    # 第一次撞到 CF：解一次挑战，拿到 cf_clearance 后重试
                    if solver.enabled and not flare_cookies:
                        try:
                            solved = solver.get(full, force=flare_retried)
                            if solved:
                                flare_cookies, flare_ua = solved
                                flare_retried = True
                                log.info("cloudflare: retrying %s with clearance cookie", full)
                                continue
                        except Exception as exc:  # noqa: BLE001
                            log.warning("cloudflare solve failed for %s: %s", full, exc)
                    last = RuntimeError(f"blocked {resp.status_code} {full}")
                    log.warning("%s", last)
                    time.sleep(0.8 + attempt * 0.7)
                    continue
                if resp.status_code >= 400:
                    last = RuntimeError(f"HTTP {resp.status_code} {full}")
                    log.warning("%s", last)
                    continue
                return Response(
                    status=resp.status_code,
                    url=str(resp.url),
                    text=text if text else (body.decode("utf-8", "replace") if binary else ""),
                    content=body if binary else resp.content,
                    headers=dict(resp.headers),
                )
            except Exception as exc:  # noqa: BLE001 - transport layer
                last = exc
                log.warning("GET %s failed (%s/%s): %s", full, attempt + 1, attempts, exc)
                time.sleep(0.6 * (attempt + 1))
        raise last or RuntimeError(f"unreachable {full}")

    def head(self, url: str, *, referer: str | None = None) -> Response:
        full = url if url.startswith("http") else f"{self.base}/{url.lstrip('/')}"
        hdrs = dict(self.default_headers)
        if referer:
            hdrs["Referer"] = referer
        with self._lock:
            resp = self.session.head(full, headers=hdrs, timeout=self.timeout, proxy=self.proxy)
        return Response(resp.status_code, str(resp.url), resp.text, resp.content, dict(resp.headers))

    def close(self) -> None:
        with self._lock:
            try:
                self.session.close()
            except Exception:  # noqa: BLE001
                pass
