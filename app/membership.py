"""Membership tiers: pricing, entitlements, and playback gating."""
from __future__ import annotations

import re
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Tier definitions. `height` is the playback ceiling, `daily` is the per-day
# view cap (0 = unlimited), `days` is the pass length.
# ---------------------------------------------------------------------------
TIERS: dict[str, dict[str, Any]] = {
    "free": {
        "key": "free",
        "name": "游客",
        "price": 0,
        "days": 0,
        "height": 480,
        "daily": 5,
        "ads": True,
        "devices": 1,
        "downloads": 0,
        "badge": "",
    },
    "week": {
        "key": "week",
        "name": "周卡",
        "price": 15,
        "days": 7,
        "height": 1080,
        "daily": 0,
        "ads": False,
        "devices": 1,
        "downloads": 0,
        "badge": "短期尝鲜",
    },
    "month": {
        "key": "month",
        "name": "月卡",
        "price": 39,
        "days": 30,
        "height": 1080,
        "daily": 0,
        "ads": False,
        "devices": 2,
        "downloads": 0,
        "badge": "",
    },
    "year": {
        "key": "year",
        "name": "年卡",
        "price": 299,
        "days": 365,
        "height": 1080,
        "daily": 0,
        "ads": False,
        "devices": 3,
        "downloads": 10,
        "badge": "省 36% · 主推",
        "featured": True,
    },
    "lifetime": {
        "key": "lifetime",
        "name": "终身",
        "price": 699,
        "days": 0,
        "height": 1080,
        "daily": 0,
        "ads": False,
        "devices": 3,
        "downloads": 10,
        "badge": "限量 100 份",
    },
    # 隐藏档：活动/客服手动发放，不在定价页展示
    "trial": {
        "key": "trial",
        "name": "体验 3 天",
        "price": 0,
        "days": 3,
        "height": 720,
        "daily": 0,
        "ads": False,
        "devices": 1,
        "downloads": 0,
        "badge": "活动发放",
    },
}

# purchase order shown on the pricing page
PLAN_ORDER = ("week", "month", "year", "lifetime")

FEATURE_MATRIX: list[dict[str, Any]] = [
    {"label": "画质上限", "free": "480p", "member": "1080p"},
    {"label": "每日观看", "free": "5 部", "member": "无限"},
    {"label": "广告", "free": "有", "member": "无"},
    {"label": "下载", "free": "—", "member": "年付每日 10 部"},
    {"label": "收藏 / 记录同步", "free": "仅本地", "member": "云端"},
    {"label": "同时播放设备", "free": "1", "member": "2–3"},
]

_RES_RE = re.compile(r"(\d{3,4})\s*x\s*(\d{3,4})")


def get(tier: str | None) -> dict[str, Any]:
    return TIERS.get((tier or "free").lower(), TIERS["free"])


def max_height(tier: str | None) -> int:
    return int(get(tier)["height"])


def public_plans() -> dict[str, Any]:
    plans = []
    for key in PLAN_ORDER:
        t = TIERS[key]
        per_month = round(t["price"] / (t["days"] / 30), 1) if t["days"] else None
        per_day = round(t["price"] / t["days"], 2) if t["days"] else None
        plans.append(
            {
                "key": t["key"],
                "name": t["name"],
                "price": t["price"],
                "days": t["days"],
                "per_month": per_month,
                "per_day": per_day,
                "badge": t.get("badge", ""),
                "featured": bool(t.get("featured")),
                "height": t["height"],
                "devices": t["devices"],
            }
        )
    return {
        "plans": plans,
        "free": {k: TIERS["free"][k] for k in ("name", "height", "daily", "ads", "devices")},
        "matrix": FEATURE_MATRIX,
    }


def _height_of(media: dict[str, Any]) -> int:
    for field in ("quality", "label"):
        m = _RES_RE.search(str(media.get(field, "")))
        if m:
            return int(m.group(2))
    mapping = {"480p": 480, "720p": 720, "1080p": 1080, "360p": 360}
    for field in ("quality", "label"):
        v = str(media.get(field, "")).lower()
        if v in mapping:
            return mapping[v]
    return 0  # unknown / master playlist


def filter_media(media: Iterable[dict[str, Any]], tier: str | None) -> list[dict[str, Any]]:
    """Return playable media allowed for this tier, best quality first."""
    items = list(media)
    if not items:
        return []
    ceiling = max_height(tier)
    allowed = [m for m in items if 0 < _height_of(m) <= ceiling]
    if allowed:
        return sorted(allowed, key=lambda m: -_height_of(m))
    # nothing fits the ceiling: fall back to the lowest available quality
    return sorted(items, key=lambda m: _height_of(m) or 10**6)[:1]


def can_watch(tier: str | None, views_today: int) -> bool:
    limit = int(get(tier)["daily"])
    return limit == 0 or views_today < limit
