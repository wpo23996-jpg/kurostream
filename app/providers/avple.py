"""AVPle — Next.js site, everything lives in __NEXT_DATA__ (including the m3u8)."""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, Media, SearchResult
from .base import BaseProvider, ProviderError

VID_RE = re.compile(r"/video/(\d+)")
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
M3U8_RE = re.compile(r"https?://[^\s\"'<>\\]+\.m3u8[^\s\"'<>\\]*")
MP4_RE = re.compile(r"https?://[^\s\"'<>\\]+\.mp4[^\s\"'<>\\]*")


def _walk_urls(obj, pattern) -> list[str]:
    out: list[str] = []

    def visit(node):
        if isinstance(node, dict):
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)
        elif isinstance(node, str):
            for m in pattern.findall(node):
                if m not in out:
                    out.append(m)

    visit(obj)
    return out


class AvpleProvider(BaseProvider):
    key = "avple"
    label = "亚洲综合"
    lang = "zh"
    kinds = ("search", "browse", "detail", "media")
    hosts = ("avple.tv", "asserts.avple.tv", "assert.avple.tv", "aoskkzzay.com")

    base = "https://avple.tv"

    def __init__(self) -> None:
        super().__init__()
        self.http.base = self.base

    # ------------------------------------------------------------------ parsing
    def _cards(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")
        items: list[Item] = []
        seen: set[str] = set()
        for a in soup.select("a[href^='/video/']"):
            m = VID_RE.search(a.get("href", ""))
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            img = a.select_one("img[src]")
            h2 = a.select_one("h2")
            container = a.parent
            dur = None
            for _ in range(3):
                if container is None:
                    break
                dur = container.select_one("div.absolute.bottom-2.right-2")
                if dur:
                    break
                container = container.parent
            items.append(
                Item(
                    provider=self.key,
                    id=vid,
                    title=(h2.get_text(" ", strip=True) if h2 else (img.get("alt", "") if img else vid)),
                    cover=(img.get("src", "") if img else ""),
                    url=f"{self.base}/video/{vid}",
                    duration=dur.get_text(strip=True) if dur else "",
                )
            )
        return items

    # --------------------------------------------------------------- operations
    def search(self, query: str, page: int = 1) -> SearchResult:
        url = f"{self.base}/search?key={quote(query, safe='')}"
        html = self.http.get(url, params={"page": page} if page > 1 else None).text
        items = self._cards(html)
        pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
        return SearchResult(items=items, page=page, total_pages=max(pages) if pages else 1)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        # 实测：/?page=N 无效（永远同一批），/tags/all/{page}/date 才是真分页
        if page <= 1:
            routes = ["/home", "/"]
        else:
            routes = [f"/tags/all/{page}/date", "/home"]
        last: Exception | None = None
        for route in routes:
            try:
                html = self.http.get(f"{self.base}{route}").text
                items = self._cards(html)
                if items:
                    return SearchResult(items=items, page=page, total_pages=self.pages_of(html))
            except Exception as exc:  # noqa: BLE001
                last = exc
        if last:
            raise last
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        url = f"{self.base}/video/{vid}"
        html = self.http.get(url).text
        m = NEXT_RE.search(html)
        if not m:
            raise ProviderError("avple: __NEXT_DATA__ missing")
        data = json.loads(m.group(1))
        props = data.get("props", {}).get("pageProps", {}) or {}
        node = props.get("instance") or {}
        if not isinstance(node, dict):
            node = {}

        # play lives as a relative path like "hls/<id>/playlist.m3u8"
        host = props.get("host") or "avple.tv"
        media: list[Media] = []
        play = node.get("play") or ""
        if play:
            full = play if play.startswith("http") else f"https://{host}/{play.lstrip('/')}"
            kind = "hls" if ".m3u8" in full else "mp4"
            media.append(Media(url=full, kind=kind, quality="auto", label=kind.upper(), headers={"Referer": url}))
        for u in _walk_urls(data, M3U8_RE):
            if u not in [x.url for x in media]:
                media.append(Media(url=u, kind="hls", quality="auto", label="HLS", headers={"Referer": url}))
        for u in _walk_urls(data, MP4_RE):
            if u not in [x.url for x in media]:
                media.append(Media(url=u, kind="mp4", quality="auto", label="MP4", headers={"Referer": url}))

        soup = BeautifulSoup(html, "lxml")
        og_t = soup.select_one("meta[property='og:title']")
        title = node.get("title") or (og_t.get("content", "") if og_t else "") or vid
        cover = node.get("img_preview") or node.get("img_normal") or ""

        tags = node.get("tags") if isinstance(node.get("tags"), list) else []
        actors = node.get("acters") if isinstance(node.get("acters"), list) else []

        item = Item(
            provider=self.key,
            id=vid,
            title=title,
            cover=cover,
            url=url,
            date=str(node.get("release", "") or ""),
            duration=str(node.get("timeLengh", "") or ""),
        )
        return Detail(
            item=item,
            description=(props.get("metaInfo") or {}).get("description", "") if isinstance(props.get("metaInfo"), dict) else "",
            actresses=[a for a in actors if isinstance(a, str)],
            genres=[t for t in tags if isinstance(t, str)][:12],
            date=str(node.get("release", "") or ""),
            duration=str(node.get("timeLengh", "") or ""),
            media=media,
            meta={"code": node.get("code", ""), "views": node.get("view_count", "")},
        )
