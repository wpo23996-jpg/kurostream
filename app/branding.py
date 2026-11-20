"""Branding layer: public catalogue keys and display names.

Internal connector keys never reach the browser: the API only speaks
"public" keys such as `jp-hd` or `anime`, so the client sees a set of
curated catalogue sections rather than upstream origins.
"""
from __future__ import annotations

# internal connector key -> (public key, display label, section blurb)
CATALOGUE: dict[str, tuple[str, str, str]] = {
    "missav": ("jp-hd", "日本高清", "高画质日本作品，含中文字幕与无码专区"),
    "jable": ("jp-select", "日本精选", "编辑精选合辑，画质稳定"),
    "avple": ("asia", "亚洲综合", "亚洲地区综合片库"),
    "hanime1": ("anime", "动画专区", "动画 / 里番专线"),
    "huangguo": ("ai-short", "AI短剧", "AI 成人短剧、漫剧与换脸改编"),
    "eporner": ("western", "欧美专区", "欧美高清资源"),
    "javbus": ("archive", "影片资料", "影片资料与下载索引"),
    "javdb": ("rating", "评分榜单", "评分、榜单与口碑数据"),
    "supjav": ("series", "系列合集", "系列作品合集索引"),
}

_PUBLIC_TO_INTERNAL = {v[0]: k for k, v in CATALOGUE.items()}


def public_key(internal: str) -> str:
    return CATALOGUE.get(internal, (internal, "资源", ""))[0]


def public_label(internal: str) -> str:
    return CATALOGUE.get(internal, (internal, "资源", ""))[1]


def public_blurb(internal: str) -> str:
    return CATALOGUE.get(internal, (internal, "资源", ""))[2]


def internal_key(public: str) -> str:
    """Accept either a public key or an internal one."""
    return _PUBLIC_TO_INTERNAL.get(public, public)


def order() -> list[str]:
    return [v[0] for v in CATALOGUE.values()]
