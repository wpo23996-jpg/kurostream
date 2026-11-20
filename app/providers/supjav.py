"""SupJav — listing + metadata; playback is behind an encrypted per-server token."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, SearchResult
from .base import BaseProvider

log = logging.getLogger("javhub.supjav")

POST_RE = re.compile(r"/(\d+)\.html")


class SupjavProvider(BaseProvider):
    key = "supjav"
    label = "系列合集"
    lang = "en"
    kinds = ("search", "browse", "detail")
    hosts = ("supjav.com", "img.supjav.com")
    notes = "系列合集索引。"

    base = "https://supjav.com"

    def __init__(self) -> None:
        super().__init__()
        self.http.base = self.base

    def _cards(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Item] = []
        seen: set[str] = set()
        for a in soup.select("a[href*='supjav.com']"):
            href = a.get("href", "")
            m = POST_RE.search(href)
            if not m:
                continue
            pid = m.group(1)
            if pid in seen:
                continue
            img = a.select_one("img")
            if img is None and a.select_one("h2,h3,p") is None:
                continue
            seen.add(pid)
            title_node = a.select_one("h2, h3, p")
            out.append(
                Item(
                    provider=self.key,
                    id=pid,
                    title=(img.get("alt") if img and img.get("alt") else (title_node.get_text(" ", strip=True) if title_node else pid)),
                    cover=(img.get("src", "") if img else ""),
                    url=href,
                )
            )
        return out

    def search(self, query: str, page: int = 1) -> SearchResult:
        url = f"{self.base}/?s={quote(query, safe='')}"
        html = self.http.get(url, params={"page": page} if page > 1 else None).text
        return SearchResult(items=self._cards(html), page=page, total_pages=1)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        route = {"new": "/", "trending": "/popular", "chinese": "/censored"}.get(sort, "/")
        for r in dict.fromkeys([route, "/"]):
            try:
                html = self.http.get(f"{self.base}{r}", params={"page": page} if page > 1 else None).text
                items = self._cards(html)
                if items:
                    return SearchResult(items=items, page=page, total_pages=self.pages_of(html))
            except Exception as exc:  # noqa: BLE001
                log.debug("supjav browse %r failed: %s", r, exc)
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        url = f"{self.base}/{vid}.html"
        html = self.http.get(url).text
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else vid
        wrap = soup.select_one("#player-wrap")
        poster = ""
        if wrap and wrap.get("style"):
            m = re.search(r"url\(([^)]+)\)", wrap["style"])
            poster = m.group(1) if m else ""
        tags = [a.get_text(strip=True) for a in soup.select("a[href*='/tag/']") if a.get_text(strip=True)]
        return Detail(
            item=Item(provider=self.key, id=vid, title=title, cover=poster, url=url),
            genres=sorted(set(tags))[:12],
            media=[],
            meta={"note": "该条目暂未接入在线播放"},
        )
