"""进度条预览图（trick-play）：从 HLS 分片截帧 → 缓存 → 给前端 hover 用。

为什么按分片做：一个 4 秒分片 + ffmpeg -ss 定位，比拉整条流快两个数量级。
缓存 key = 分片URL + 片内时间点，命中直接返回，不占 CPU。
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests as cr

from .config import PUBLIC_BASE, settings
from .proxy import b64d, host_allowed

log = logging.getLogger("kurostream.thumb")

CACHE_DIR = Path(os.getenv("KS_THUMB_DIR", "./.thumbs"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv("KS_THUMB_MAX", str(600 * 1024 * 1024)))  # 600MB 上限
WORKERS = int(os.getenv("KS_THUMB_WORKERS", "1"))                    # 1 核机器默认串行

_sem = threading.Semaphore(max(1, WORKERS))
FFMPEG = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"


def _cache_path(seg_url: str, seek: float, width: int) -> Path:
    key = hashlib.sha1(f"{seg_url}|{seek:.2f}|{width}".encode()).hexdigest()[:20]
    return CACHE_DIR / f"{key}.jpg"


def _prune() -> None:
    try:
        total = sum(p.stat().st_size for p in CACHE_DIR.glob("*.jpg"))
    except Exception:  # noqa: BLE001
        return
    if total <= MAX_BYTES:
        return
    files = sorted(CACHE_DIR.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    while files and total > MAX_BYTES * 0.8:
        f = files.pop(0)
        try:
            total -= f.stat().st_size
            f.unlink()
        except Exception:  # noqa: BLE001
            pass


def _download(seg_url: str, referer: str) -> bytes:
    resp = cr.get(
        seg_url,
        impersonate=settings.impersonate,
        timeout=25,
        headers={
            "User-Agent": settings.user_agent,
            "Referer": referer or seg_url,
            "Accept": "*/*",
        },
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"segment {resp.status_code}")
    return resp.content


def _extract_via_m3u8(seg_data: bytes, key_bytes: bytes, iv_hex: str, seek: float, width: int) -> bytes | None:
    """加密分片：包一层本地 m3u8 让 ffmpeg 走 HLS 解密路径（-decryption_key 对裸 .ts 无效）。"""
    tmpdir = tempfile.mkdtemp(prefix="kst")
    try:
        d = Path(tmpdir)
        (d / "seg.ts").write_bytes(seg_data)
        (d / "key.bin").write_bytes(key_bytes)
        key_line = '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"'
        if iv_hex:
            key_line += f",IV=0x{iv_hex}"
        (d / "play.m3u8").write_text(
            "\n".join(
                [
                    "#EXTM3U",
                    "#EXT-X-VERSION:3",
                    "#EXT-X-TARGETDURATION:10",
                    key_line,
                    "#EXTINF:10.0,",
                    "seg.ts",
                    "#EXT-X-ENDLIST",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        out = d / "out.jpg"
        for at in (seek, max(0.0, seek - 1.0), 0.0):
            cmd = [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,crypto,data",
                "-allowed_extensions", "ALL",
                "-ss", f"{max(0.0, at):.3f}",
                "-i", str(d / "play.m3u8"),
                "-frames:v", "1",
                "-vf", f"scale={width}:-2",
                "-q:v", "4",
                str(out),
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=25)
            except subprocess.TimeoutExpired:
                continue
            if r.returncode == 0 and out.exists():
                body = out.read_bytes()
                if body:
                    return body
            if at <= 0.0:
                break
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_once(data: bytes, seek: float, width: int, key_hex: str = "") -> bytes | None:
    with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    out_path = tmp_path + ".jpg"
    try:
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
        if key_hex:
            cmd += ["-decryption_key", key_hex]
        cmd += [
            "-ss", f"{max(0.0, seek):.3f}",
            "-i", tmp_path,
            "-frames:v", "1",
            "-vf", f"scale={width}:-2",
            "-q:v", "4",
            out_path,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=25)
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0 or not Path(out_path).exists():
            return None
        body = Path(out_path).read_bytes()
        return body or None
    finally:
        for p in (tmp_path, out_path):
            try:
                Path(p).unlink()
            except Exception:  # noqa: BLE001
                pass


def _extract(data: bytes, seek: float, width: int, key_hex: str = "") -> bytes:
    """先按目标时间截，失败就退回分片开头（末尾几秒经常定位超出）。"""
    pic = _extract_once(data, seek, width, key_hex)
    if pic is None and seek > 0.4:
        pic = _extract_once(data, max(0.0, seek - 1.0), width, key_hex)
    if pic is None and seek > 0.1:
        pic = _extract_once(data, 0.0, width, key_hex)
    if pic is None:
        raise RuntimeError("ffmpeg 截帧失败（明文分片也失败了）")
    return pic


def _download_key(key_url: str, referer: str = "") -> bytes:
    resp = cr.get(
        key_url,
        impersonate=settings.impersonate,
        timeout=20,
        headers={
            "User-Agent": settings.user_agent,
            "Referer": referer or key_url,
            "Accept": "*/*",
        },
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"key {resp.status_code}")
    body = resp.content
    if len(body) < 16:
        raise RuntimeError(f"key 长度异常 {len(body)}")
    return body[:16]


def fetch_key(key_url: str, referer: str = "") -> str:
    """下载 AES-128 密钥，返回 ffmpeg 需要的 hex 字符串。"""
    return _download_key(key_url, referer).hex()


def get_thumb(seg_u: str, seek: float, referer_u: str = "", width: int = 320,
              key_u: str = "", iv_hex: str = "") -> bytes:
    seg_url = b64d(seg_u)
    referer = b64d(referer_u) if referer_u else ""
    if not host_allowed(seg_url):
        raise ValueError("segment host not allowed")

    key_url = b64d(key_u) if key_u else ""
    if key_url and not host_allowed(key_url):
        key_url = ""

    cache = _cache_path(seg_url, seek, width)
    if cache.exists() and cache.stat().st_size > 0:
        return cache.read_bytes()

    with _sem:
        if cache.exists():  # 等锁期间别人已经生成
            return cache.read_bytes()
        data = _download(seg_url, referer)

        pic = None
        if key_url:
            try:
                key_bytes = _download_key(key_url, referer)
                pic = _extract_via_m3u8(data, key_bytes, iv_hex, seek, width)
            except Exception as exc:  # noqa: BLE001
                log.debug("thumb decrypt path failed: %s", exc)
        if pic is None:
            pic = _extract(data, seek, width)

        try:
            cache.write_bytes(pic)
        except Exception:  # noqa: BLE001
            pass
        _prune()
        return pic


def stats() -> dict:
    try:
        files = list(CACHE_DIR.glob("*.jpg"))
        size = sum(p.stat().st_size for p in files)
    except Exception:  # noqa: BLE001
        files, size = [], 0
    return {"count": len(files), "bytes": size, "dir": str(CACHE_DIR)}
