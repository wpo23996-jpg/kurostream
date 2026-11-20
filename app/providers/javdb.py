"""JavDB — metadata + magnet links, plus a playable preview for some entries."""
from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, Media, SearchResult
from .base import BaseProvider

VID_RE = re.compile(r"/v/([A-Za-z0-9]+)")


class JavdbProvider(BaseProvider):
    key = "javdb"
    label = "评分榜单"
    lang = "zh"
    kinds = ("search", "browse", "detail")
    hosts = ("javdb.com", "c0.jdbstatic.com", "jdbstatic.com")
    notes = "评分与榜单数据，部分条目带试看。"

    base = "https://javdb.com"

    def __init__(self) -> None:
        super().__init__()
        self.http.base = self.base
        self.http.default_headers["Cookie"] = "over18=1; locale=zh"

    def _cards(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Item] = []
        seen: set[str] = set()
        for box in soup.select("div.item > a.box[href^='/v/']"):
            m = VID_RE.search(box.get("href", ""))
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            img = box.select_one("img")
            title_node = box.select_one("div.video-title") or box.select_one("strong")
            meta_node = box.select_one("div.meta")
            out.append(
                Item(
                    provider=self.key,
                    id=vid,
                    title=(title_node.get_text(" ", strip=True) if title_node else box.get("title", vid)),
                    cover=(img.get("src", "") if img else ""),
                    url=f"{self.base}/v/{vid}",
                    date=meta_node.get_text(strip=True) if meta_node else "",
                )
            )
        return out

    def search(self, query: str, page: int = 1) -> SearchResult:
        url = f"{self.base}/search?q={quote(query, safe='')}&f=all"
        html = self.http.get(url, params={"page": page} if page > 1 else None).text
        items = self._cards(html)
        pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
        return SearchResult(items=items, page=page, total_pages=max(pages) if pages else 1)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        route = {"new": "/", "trending": "/hot", "chinese": "/sub"}.get(sort, "/")
        routes = [route, "/"] if route != "/" else ["/"]
        last: Exception | None = None
        for r in routes:
            try:
                html = self.http.get(f"{self.base}{r}", params={"page": page} if page > 1 else None).text
                items = self._cards(html)
                if items:
                    return SearchResult(items=items, page=page, total_pages=self.pages_of(html))
            except Exception as exc:  # noqa: BLE001
                last = exc
        if last:
            raise last
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        url = f"{self.base}/v/{vid}"
        html = self.http.get(url).text
        soup = BeautifulSoup(html, "lxml")

        title_node = soup.select_one("h2.title") or soup.select_one("h2")
        title = title_node.get_text(" ", strip=True) if title_node else vid

        magnets = []
        for a in soup.select("a[href^='magnet:']"):
            magnets.append({"name": a.get_text(" ", strip=True) or vid, "magnet": a["href"], "size_bytes": None})

        genres = [a.get_text(strip=True) for a in soup.select("a[href*='/tags/']") if a.get_text(strip=True)]
        actresses = [a.get_text(strip=True) for a in soup.select("a[href*='/actors/']") if a.get_text(strip=True)]

        media: list[Media] = []
        for v in soup.select("video source[src]") + soup.select("video[src]"):
            src = v.get("src", "")
            if src and (".m3u8" in src or ".mp4" in src):
                media.append(Media(url=src, kind="hls" if ".m3u8" in src else "mp4",
                                   quality="auto", label="preview", headers={"Referer": url}))

        cover = soup.select_one("div.column-video-cover img") or soup.select_one("img.video-cover")
        date_node = soup.select_one("div.meta") or soup.select_one("span.value")
        return Detail(
            item=Item(provider=self.key, id=vid, title=title,
                      cover=cover.get("src", "") if cover else "", url=url,
                      date=date_node.get_text(strip=True) if date_node else ""),
            actresses=actresses[:10],
            genres=genres[:12],
            media=media,
            magnets=magnets,
            related=self._cards(html)[:12],
        )
