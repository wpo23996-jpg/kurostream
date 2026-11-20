"""HLS 分片磁盘缓存（LRU）。

分片内容不可变（同一 URL 永远是同一段视频），所以可以放心长期缓存。
命中后直接返回，不再回源，拖动进度条、重复观看都是秒开。
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger("kurostream.segcache")

DIR = Path(os.getenv("KS_SEG_CACHE", "./.segcache"))
DIR.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv("KS_SEG_CACHE_MAX", str(1024 * 1024 * 1024)))  # 1 GB
MAX_ITEM = int(os.getenv("KS_SEG_ITEM_MAX", str(4 * 1024 * 1024)))       # 单分片上限 4MB

_lock = threading.Lock()
_index: dict[str, int] = {}   # key -> size
_total = 0


def _key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:26]


def _load_index() -> None:
    global _total
    try:
        for p in DIR.glob("*.bin"):
            sz = p.stat().st_size
            _index[p.stem] = sz
            _total += sz
    except Exception:  # noqa: BLE001
        pass
    log.info("segcache: %d files, %.1f MB", len(_index), _total / 1048576)


_load_index()


def get(url: str) -> bytes | None:
    k = _key(url)
    p = DIR / f"{k}.bin"
    try:
        if not p.exists():
            return None
        data = p.read_bytes()
        try:
            p.touch()  # LRU：命中就更新 mtime
        except Exception:  # noqa: BLE001
            pass
        return data
    except Exception:  # noqa: BLE001
        return None


def put(url: str, data: bytes) -> None:
    global _total
    if not data or len(data) > MAX_ITEM:
        return
    k = _key(url)
    if k in _index:
        return
    p = DIR / f"{k}.bin"
    try:
        p.write_bytes(data)
    except Exception:  # noqa: BLE001
        return
    with _lock:
        _index[k] = len(data)
        _total += len(data)
    if _total > MAX_BYTES:
        prune()


def prune() -> None:
    """按 mtime 从旧到新删，直到降到 80%。"""
    global _total
    try:
        files = sorted(DIR.glob("*.bin"), key=lambda x: x.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return
    target = MAX_BYTES * 0.8
    with _lock:
        for f in files:
            if _total <= target:
                break
            try:
                sz = f.stat().st_size
                f.unlink()
                _index.pop(f.stem, None)
                _total = max(0, _total - sz)
            except Exception:  # noqa: BLE001
                pass


def stats() -> dict:
    with _lock:
        return {"files": len(_index), "bytes": _total, "max": MAX_BYTES, "dir": str(DIR)}
