"""Global settings for the KuroStream platform."""
from __future__ import annotations

import os
from dataclasses import dataclass

SITE_NAME = os.getenv("KS_SITE_NAME", "KuroStream")
SITE_TAGLINE = os.getenv("KS_TAGLINE", "高清片库 · 极速播放")

# 对外访问的绝对地址，例如 https://kuro.example.com
# 网页同源访问可以留空；打包成 iOS / Android 外壳时必须填，
# 否则外壳里的相对路径 /api/media/... 会指向 capacitor://localhost 而不是你的服务器
PUBLIC_BASE = os.getenv("KS_PUBLIC_BASE", "").rstrip("/")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # network
    impersonate: str = "chrome"
    timeout: float = 30.0
    retries: int = 3
    min_interval: float = 0.35
    proxy: str | None = None
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    accept_language: str = "zh-CN,zh;q=0.9,en;q=0.8"

    # behaviour
    cache_ttl: int = 300
    search_page_size: int = 24
    default_max_height: int = 1080

    # proxy allow-list (suffix match), extended by each provider's own hosts
    allowed_media_hosts: tuple[str, ...] = (
        "surrit.com",
        "fourhoi.com",
        "mushroomtrack.com",
        "jable.tv",
        "assets-cdn.jable.tv",
        "hembed.com",
        "vdownload.hembed.com",
        "avple.tv",
        "asserts.avple.tv",
        "aoskkzzay.com",
        "eporner.com",
        "static-ca-cdn.eporner.com",
        "static.eporner.com",
        "missav.ws",
        "missav123.com",
        "missav.ai",
        "supjav.com",
        "img.supjav.com",
        "javdb.com",
        "javbus.com",
        "cdn.javbus.com",
    )


settings = Settings()

# ---- environment overrides (production tuning without touching code) ----
settings.timeout = _env_float("KS_TIMEOUT", settings.timeout)
settings.retries = _env_int("KS_RETRIES", settings.retries)
settings.min_interval = _env_float("KS_MIN_INTERVAL", settings.min_interval)
settings.cache_ttl = _env_int("KS_CACHE_TTL", settings.cache_ttl)
settings.proxy = os.getenv("KS_PROXY") or settings.proxy
settings.impersonate = os.getenv("KS_IMPERSONATE", settings.impersonate)

# image hosts that enforce hotlink protection -> the referer to send
IMAGE_REFERERS: dict[str, str] = {
    "fourhoi.com": "https://missav.ws/",
    "surrit.com": "https://missav.ws/",
    "assets-cdn.jable.tv": "https://jable.tv/",
    "jable.tv": "https://jable.tv/",
    "asserts.avple.tv": "https://avple.tv/",
    "assert.avple.tv": "https://avple.tv/",
    "avple.tv": "https://avple.tv/",
    "hembed.com": "https://hanime1.me/",
    "vdownload.hembed.com": "https://hanime1.me/",
    "hanime1.me": "https://hanime1.me/",
    "jdbstatic.com": "https://javdb.com/",
    "c0.jdbstatic.com": "https://javdb.com/",
    "cdn.javbus.com": "https://www.javbus.com/",
    "javbus.com": "https://www.javbus.com/",
    "img.supjav.com": "https://supjav.com/",
    "supjav.com": "https://supjav.com/",
    "eporner.com": "https://www.eporner.com/",
    "static-ca-cdn.eporner.com": "https://www.eporner.com/",
}
