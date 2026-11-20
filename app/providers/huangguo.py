"""黄果短剧（HGhub 上游）：AI 成人短剧 / 漫剧。

协议（2026-11 实测）：
  列表   GET  /ai-duanju/ 、/ai-duanju/{page}/ ，卡片 /video/{id}/
  详情   GET  /video/{id}/  ，集数在「更新至 N 集」
  播放   POST /api/videos/{id}/episodes/{ep}/playback    body 必须是 {}
         → data.streams.main 为 HLS 清单，AES-128 加密
         清单/key/分片都在 CDN，auth_key 已内嵌在 URL 里
"""
from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

from ..schemas import Detail, Item, Media, SearchResult
from .base import BaseProvider, ProviderError

log = logging.getLogger("javhub.huangguo")

BASE = "https://huangguoai.com"
VIDEO_RE = re.compile(r"/video/(\d+)/?")
EP_COUNT_RES = (
    re.compile(r"更新至\s*(\d+)\s*集"),
    re.compile(r'data-show-ep="(\d+)"'),
    re.compile(r"第\s*(\d+)\s*集"),
)

ROUTES = {
    "new": "/ai-duanju/",
    "trending": "/rank/",
    "chinese": "/ai-manju/",
    "manju": "/ai-manju/",
    "original": "/video_original/",
}


class HuangguoProvider(BaseProvider):
    key = "huangguo"
    label = "AI短剧"
    lang = "zh"
    kinds = ("search", "browse", "detail", "media")
    hosts = (
        "huangguoai.com",
        "huangguoai.ai",
        "qnlycc.cn",
        "tjyyjk.cn",
        "drleao.cn",
        "hzjvlo.cn",
        "eisees.com",
    )
    notes = "AI 成人短剧 / 漫剧 / 换脸改编，AES-128 HLS"

    base = BASE

    def __init__(self) -> None:
        super().__init__()
        self.http.base = BASE
        self.http.default_headers.update(
            {
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": BASE + "/",
            }
        )

    # ------------------------------------------------------------------ parsing
    def _cards(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")

        # 先收集所有视频链接（id -> 标题/地址），保证顺序
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        for a in soup.select("a[href*='/video/']"):
            m = VIDEO_RE.search(a.get("href", ""))
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            links.append((vid, a.get_text(" ", strip=True)))

        if not links:
            return []

        # 再收集所有封面图（data-src 优先，跳过占位图/图标）
        covers: list[str] = []
        for img in soup.select("img"):
            src = (
                img.get("data-src")
                or img.get("data-original")
                or img.get("data-lazy-src")
                or img.get("src")
                or ""
            )
            if not src or src.startswith("data:"):
                continue
            if any(bad in src for bad in ("/static/", "cover-placeholder", "yandex", ".svg")):
                continue
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = BASE + src
            covers.append(src)

        out: list[Item] = []
        for idx, (vid, title) in enumerate(links):
            # 卡片图与链接通常同序；数量对不上时按比例取，避免整页没图
            cover = covers[idx] if idx < len(covers) else ""
            if not cover and covers:
                cover = covers[min(len(covers) - 1, int(idx * len(covers) / max(1, len(links))))]
            out.append(
                Item(
                    provider=self.key,
                    id=vid,
                    title=title or vid,
                    cover=cover,
                    url=f"{BASE}/video/{vid}/",
                )
            )
        return out

    @staticmethod
    def _episode_count(html: str) -> int:
        for rx in EP_COUNT_RES:
            m = rx.search(html)
            if m:
                try:
                    return max(1, int(m.group(1)))
                except (ValueError, IndexError):
                    continue
        return 1

    # --------------------------------------------------------------- operations
    def search(self, query: str, page: int = 1) -> SearchResult:
        from urllib.parse import quote

        url = f"{BASE}/search/video/{quote(query, safe='')}/"
        if page > 1:
            url += f"{page}/"
        try:
            html = self.http.get(url).text
        except Exception:  # noqa: BLE001
            return SearchResult(items=[], page=page, total_pages=1)
        return SearchResult(items=self._cards(html), page=page, total_pages=1)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        route = ROUTES.get(sort, ROUTES["new"])
        url = f"{BASE}{route}" if page <= 1 else f"{BASE}{route}{page}/"
        html = ""
        try:
            html = self.http.get(url).text
        except Exception as exc:  # noqa: BLE001 - fall back to the default channel
            log.debug("huangguo browse %s failed: %s", url, exc)
            try:
                html = self.http.get(f"{BASE}{ROUTES['new']}").text
            except Exception:  # noqa: BLE001
                return SearchResult(items=[], page=page, total_pages=1)
        items = self._cards(html)
        pages = [int(n) for n in re.findall(r'data-pages="(\d+)"', html)]
        if not items:
            return SearchResult(items=[], page=page, total_pages=1)
        return SearchResult(items=items, page=page, total_pages=max(pages) if pages else 1, total=None)

    def detail(self, vid: str) -> Detail:
        url = f"{BASE}/video/{vid}/"
        html = self.http.get(url).text
        soup = BeautifulSoup(html, "lxml")

        og_t = soup.select_one("meta[property='og:title']")
        title = (og_t.get("content", "") if og_t else "").replace(" - 黄果短剧", "").strip() or vid
        og_i = soup.select_one("meta[property='og:image']")
        cover = og_i.get("content", "") if og_i else ""
        og_d = soup.select_one("meta[property='og:description']")
        desc = og_d.get("content", "") if og_d else ""

        eps = self._episode_count(html)
        media: list[Media] = []
        for ep in range(1, min(eps, 3) + 1):
            try:
                media.append(self._playback(vid, ep))
            except Exception as exc:  # noqa: BLE001
                log.debug("huangguo playback %s ep%d failed: %s", vid, ep, exc)
                break

        if not media:
            raise ProviderError("huangguo: 播放地址解析失败（可能已下架或接口变更）")

        item = Item(
            provider=self.key,
            id=vid,
            title=title,
            cover=cover,
            url=url,
            duration=f"{eps} 集",
        )
        return Detail(
            item=item,
            description=desc,
            genres=["AI短剧"],
            media=media,
            related=[],
            meta={"episodes": eps, "source": "huangguo"},
        )

    # ------------------------------------------------------------------ play
    def _playback(self, vid: str, ep: int) -> Media:
        api = f"{BASE}/api/videos/{vid}/episodes/{ep}/playback"
        headers = {
            "Content-Type": "application/json",
            "Origin": BASE,
            "Referer": f"{BASE}/video/{vid}/",
        }
        resp = cr.post(api, headers=headers, data="{}", impersonate="chrome", timeout=30)
        if resp.status_code >= 400:
            raise ProviderError(f"playback HTTP {resp.status_code}")

        try:
            data = resp.json().get("data") or {}
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("playback 返回非 JSON") from exc

        streams = data.get("streams") or {}
        main = streams.get("main") or streams.get("hevc") or ""
        main = main.replace("\\u0026", "&")
        if not main:
            raise ProviderError("playback 没有 streams.main")

        return Media(
            url=main,
            kind="hls",
            quality=f"第{ep}集",
            label=f"EP{ep}",
            headers={"Referer": f"{BASE}/video/{vid}/"},
        )
