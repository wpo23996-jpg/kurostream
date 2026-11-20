"""Cloudflare 挑战破解：FlareSolverr 解一次 → 缓存 cookie → curl_cffi 秒级复用。

原理：
  FlareSolverr 用真实 Chromium 过掉 JS/managed challenge，吐出 cf_clearance +
  它自己的 User-Agent。cf_clearance 绑定「IP + UA」，所以后续请求必须带同一套
  cookie 和 UA，用 curl_cffi 发（TLS 指纹够像就过）。

缓存落盘，重启服务不用重解。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests as cr

log = logging.getLogger("kurostream.cf")

ENDPOINT = os.getenv("KS_FLARESOLVERR", "").strip()
CACHE_FILE = Path(os.getenv("KS_CF_CACHE", "./.cf_sessions.json"))
TTL = int(os.getenv("KS_CF_TTL", "1800"))

_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.debug("cache write failed: %s", exc)


class Solver:
    def __init__(self, endpoint: str = ENDPOINT, ttl: int = TTL) -> None:
        self.endpoint = endpoint
        self.ttl = ttl
        self.enabled = bool(endpoint)

    # ------------------------------------------------------------------ public
    def get(self, url: str, force: bool = False) -> tuple[dict[str, str], str] | None:
        """Return (cookies, user_agent) for the URL's host, solving if needed."""
        if not self.enabled:
            return None
        host = urlparse(url).hostname or ""
        if not host:
            return None

        if not force:
            with _lock:
                hit = _load().get(host)
            if hit and hit.get("ts", 0) + self.ttl > time.time():
                return hit.get("cookies", {}), hit.get("ua", "")

        cookies, ua = self._solve(url)
        with _lock:
            data = _load()
            data[host] = {"cookies": cookies, "ua": ua, "ts": time.time()}
            _save(data)
        return cookies, ua

    def invalidate(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        with _lock:
            data = _load()
            if host in data:
                data.pop(host)
                _save(data)

    # ----------------------------------------------------------------- private
    def _solve(self, url: str) -> tuple[dict[str, str], str]:
        log.info("cloudflare: solving challenge for %s", url)
        t0 = time.time()
        r = cr.post(
            self.endpoint,
            json={"cmd": "request.get", "url": url, "maxTimeout": 90000},
            timeout=150,
        )
        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"flaresolverr 返回非 JSON: {r.status_code}") from exc

        if data.get("status") != "ok":
            raise RuntimeError(f"flaresolverr: {data.get('message', 'unknown')}")

        sol = data.get("solution") or {}
        cookies = {c["name"]: c["value"] for c in sol.get("cookies", [])}
        ua = sol.get("userAgent", "")
        log.info(
            "cloudflare: solved %s in %.1fs, cookies=%s",
            url, time.time() - t0, list(cookies),
        )
        return cookies, ua


solver = Solver()
