"""Jable.tv — KVS-style site, plain `var hlsUrl = '...'` HLS source."""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, Media, SearchResult
from .base import BaseProvider, ProviderError

log = logging.getLogger("javhub.jable")

SLUG_RE = re.compile(r"/videos/([^/?#]+)/?")
HLS_RE = re.compile(r"var\s+hlsUrl\s*=\s*'([^']+)'")


class JableProvider(BaseProvider):
    key = "jable"
    label = "日本精选"
    lang = "zh"
    kinds = ("search", "browse", "detail", "media")
    hosts = ("jable.tv", "assets-cdn.jable.tv", "mushroomtrack.com")

    base = "https://jable.tv"

    def __init__(self) -> None:
        super().__init__()
        self.http.base = self.base

    # ------------------------------------------------------------------ parsing
    def _cards(self, html: str) -> tuple[list[Item], int]:
        soup = BeautifulSoup(html, "lxml")
        items: list[Item] = []
        seen: set[str] = set()
        for box in soup.select("div.video-img-box"):
            a = box.select_one("a[href*='/videos/']")
            if not a:
                continue
            m = SLUG_RE.search(a["href"])
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            img = box.select_one("img[data-src]") or box.select_one("img")
            title_node = box.select_one("h6.title a") or box.select_one("h6 a")
            dur = box.select_one("span.label")
            items.append(
                Item(
                    provider=self.key,
                    id=slug,
                    title=(title_node.get_text(" ", strip=True) if title_node else slug),
                    cover=(img.get("data-src") or img.get("src") or "") if img else "",
                    preview=img.get("data-preview", "") if img else "",
                    url=f"{self.base}/videos/{slug}/",
                    duration=dur.get_text(strip=True) if dur else "",
                )
            )
        pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
        return items, max(pages) if pages else 1

    # --------------------------------------------------------------- operations
    def search(self, query: str, page: int = 1) -> SearchResult:
        from urllib.parse import quote

        url = f"{self.base}/search/{quote(query, safe='')}/"
        html = self.http.get(url, params={"page": page} if page > 1 else None).text
        items, pages = self._cards(html)
        return SearchResult(items=items, page=page, total_pages=pages)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        routes = {
            "new": "/latest-updates/",
            "trending": "/hot/",
            "chinese": "/hot/",
        }.get(sort, "/")
        last: Exception | None = None
        for route in dict.fromkeys([routes, "/"]):
            try:
                html = self.http.get(
                    f"{self.base}{route}", params={"page": page} if page > 1 else None
                ).text
                items, pages = self._cards(html)
                if items:
                    return SearchResult(items=items, page=page, total_pages=pages)
            except Exception as exc:  # noqa: BLE001 - fall back to the home feed
                last = exc
        if last:
            log.debug("jable browse fallback exhausted: %s", last)
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        url = f"{self.base}/videos/{vid}/"
        html = self.http.get(url).text
        soup = BeautifulSoup(html, "lxml")

        m = HLS_RE.search(html)
        media: list[Media] = []
        playlist = soup.select_one("#player source[src]") or soup.select_one("video source[src]")
        if m:
            media.append(Media(url=m.group(1), kind="hls", quality="auto", label="HLS", headers={"Referer": url}))
        elif playlist:
            src = playlist.get("src", "")
            kind = "hls" if ".m3u8" in src else "mp4"
            media.append(Media(url=src, kind=kind, quality="auto", label=kind.upper(), headers={"Referer": url}))
        if not media:
            raise ProviderError("jable: no hlsUrl found (login-required or removed)")

        og = soup.select_one("meta[property='og:title']")
        if og and og.get("content"):
            title = og["content"].strip()
        else:
            t = soup.select_one("title")
            title = t.get_text(strip=True) if t else vid
            title = re.sub(r"\s*-\s*Jable\.TV.*$", "", title).strip()
        h6 = soup.select_one("h6.title a")
        if (not title or title == vid) and h6:
            title = h6.get_text(" ", strip=True)
        poster = soup.select_one("video[poster]")
        cover = poster.get("poster", "") if poster else ""

        info: dict[str, str] = {}
        for row in soup.select("div.info-header div.row, div.video-info div.row"):
            label = row.select_one("span.header")
            value = row.select_one("span.value, a")
            if label and value:
                info[label.get_text(strip=True)] = value.get_text(" ", strip=True)

        actresses = [a.get_text(strip=True) for a in soup.select("a[href*='/models/']") if a.get_text(strip=True)]
        genres = [a.get_text(strip=True) for a in soup.select("a[href*='/tags/']") if a.get_text(strip=True)]
        date = ""
        for key in ("發行日期", "发布", "Date", "日期", "配信開始日"):
            if key in info:
                date = info[key]
                break

        item = Item(provider=self.key, id=vid, title=title, cover=cover, url=url, date=date)
        related_items, _ = self._cards(html)
        return Detail(
            item=item,
            description=(soup.select_one("meta[name='description']").get("content", "") if soup.select_one("meta[name='description']") else ""),
            actresses=actresses,
            genres=sorted(set(genres))[:12],
            maker=info.get("片商", "") or info.get("Maker", ""),
            date=date,
            duration=info.get("時長", "") or info.get("Duration", ""),
            media=media,
            related=[i for i in related_items if i.id != vid][:12],
            meta=info,
        )
