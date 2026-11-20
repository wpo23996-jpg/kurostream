"""Cloudflare 挑战破解：FlareSolverr 解一次 → 缓存 cookie → curl_cffi 秒级复用。

要点：
  * cf_clearance 绑定「IP + UA」，解完必须用同一套 cookie + UA 发请求
  * FlareSolverr 单实例只能串行处理，必须加跨进程锁，否则多 worker 会把它堵死
  * 按 host 解（https://host/），不要用深层路径，cookie 对所有路径生效
  * 缓存落盘，重启不用重解
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests as cr

log = logging.getLogger("kurostream.cf")

ENDPOINT = os.getenv("KS_FLARESOLVERR", "").strip()
CACHE_FILE = Path(os.getenv("KS_CF_CACHE", "./.cf_sessions.json"))
TTL = int(os.getenv("KS_CF_TTL", "2400"))  # 40 分钟：比站点实际有效期短，留出重建余量
MAX_TIMEOUT_MS = int(os.getenv("KS_CF_MAX_TIMEOUT", "150000"))

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


def _origin(url: str) -> str:
    """把深路径收敛到「host + 语言段」，避免 FlareSolverr 卡在重定向链上。

    https://missav.ws/cn/new      -> https://missav.ws/cn
    https://jable.tv/latest-updates/ -> https://jable.tv/
    """
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    if parts and re.fullmatch(r"[a-z]{2}(?:-[A-Za-z]+)?", parts[0]):
        return f"{p.scheme}://{p.netloc}/{parts[0]}"
    return f"{p.scheme}://{p.netloc}/"


class Solver:
    def __init__(self, endpoint: str = ENDPOINT, ttl: int = TTL) -> None:
        self.endpoint = endpoint
        self.ttl = ttl
        self.enabled = bool(endpoint)

    # ------------------------------------------------------------------ public
    def get(self, url: str, force: bool = False) -> tuple[dict[str, str], str] | None:
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

        cookies, ua = self._solve(_origin(url))
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

    def cached_hosts(self) -> list[str]:
        return list(_load().keys())

    # ----------------------------------------------------------------- private
    def _solve(self, url: str) -> tuple[dict[str, str], str]:
        # 跨进程串行：FlareSolverr 一次只能跑一个浏览器会话
        lock_path = CACHE_FILE.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lf = open(lock_path, "w")
        try:
            try:
                import fcntl

                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            except Exception:  # noqa: BLE001  (Windows 本地调试时没有 fcntl)
                pass

            log.info("cloudflare: solving %s", url)
            t0 = time.time()
            r = cr.post(
                self.endpoint,
                json={"cmd": "request.get", "url": url, "maxTimeout": MAX_TIMEOUT_MS},
                timeout=MAX_TIMEOUT_MS / 1000 + 90,
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
            if "cf_clearance" not in cookies:
                raise RuntimeError("flaresolverr 没拿到 cf_clearance")
            log.info(
                "cloudflare: solved %s in %.1fs (clearance=%s…)",
                url, time.time() - t0, cookies["cf_clearance"][:12],
            )
            return cookies, ua
        finally:
            try:
                lf.close()
            except Exception:  # noqa: BLE001
                pass


solver = Solver()
