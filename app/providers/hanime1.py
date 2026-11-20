"""Hanime1.me — Chinese hentai/里番 site, direct mp4 sources with signed URLs."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, Media, SearchResult
from .base import BaseProvider, ProviderError

log = logging.getLogger("javhub.hanime1")

WATCH_RE = re.compile(r"[?&]v=(\d+)")
SRC_RE = re.compile(r"<source[^>]+src=\"([^\"]+)\"[^>]*?(?:size=\"(\d+)\")?", re.S)
DUR_RE = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)")


class Hanime1Provider(BaseProvider):
    key = "hanime1"
    label = "动画专区"
    lang = "zh"
    kinds = ("search", "browse", "detail", "media")
    hosts = ("hanime1.me", "hembed.com", "vdownload.hembed.com")

    base = "https://hanime1.me"

    def __init__(self) -> None:
        super().__init__()
        self.http.base = self.base

    # ------------------------------------------------------------------ parsing
    def _cards(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Item] = []
        seen: set[str] = set()
        for link in soup.select("a.video-link[href*='watch?v=']"):
            href = link.get("href", "")
            m = WATCH_RE.search(href)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            img = link.select_one("img.main-thumb") or link.select_one("img")
            holder = link.find_parent("div", attrs={"title": True})
            title = (holder.get("title") if holder else "") or (img.get("alt", "") if img else vid)
            card = link.find_parent("div", class_="video-item-container") or link
            dur = card.select_one(".duration, .video-duration, span.duration")
            out.append(
                Item(
                    provider=self.key,
                    id=vid,
                    title=title.strip() or vid,
                    cover=(img.get("src", "") if img else ""),
                    url=href,
                    duration=dur.get_text(strip=True) if dur else "",
                )
            )
        return out

    # --------------------------------------------------------------- operations
    def search(self, query: str, page: int = 1) -> SearchResult:
        url = f"{self.base}/search?query={quote(query, safe='')}"
        html = self.http.get(url, params={"page": page} if page > 1 else None).text
        items = self._cards(html)
        pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
        return SearchResult(items=items, page=page, total_pages=max(pages) if pages else 1)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        # hanime1 only exposes the home feed server-side; every sort maps to it
        last: Exception | None = None
        for route in ("/",):
            try:
                html = self.http.get(
                    f"{self.base}{route}", params={"page": page} if page > 1 else None
                ).text
                items = self._cards(html)
                if items:
                    return SearchResult(items=items, page=page, total_pages=self.pages_of(html))
            except Exception as exc:  # noqa: BLE001
                last = exc
        if last:
            log.debug("hanime1 browse failed: %s", last)
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        url = f"{self.base}/watch?v={vid}"
        html = self.http.get(url).text
        soup = BeautifulSoup(html, "lxml")

        media: list[Media] = []
        video = soup.select_one("video")
        poster = video.get("poster", "") if video else ""
        for tag in soup.select("video source[src]"):
            src = tag.get("src", "")
            if not src:
                continue
            size = tag.get("size", "")
            media.append(
                Media(
                    url=src,
                    kind="mp4",
                    quality=f"{size}p" if size else "auto",
                    label=f"{size}p" if size else "MP4",
                    headers={"Referer": url},
                )
            )
        # 高清优先
        media.sort(key=lambda m: -int(m.quality.replace("p", "")) if m.quality.endswith("p") and m.quality[:-1].isdigit() else 0)
        if not media:
            raise ProviderError("hanime1: no <source> tags (region-locked or removed)")

        meta_title = soup.select_one("meta[name='title']")
        title = meta_title.get("content", "") if meta_title else vid
        title = re.sub(r"\s*-\s*H[動动]漫.*$", "", title).strip()

        h1 = soup.select_one("h1") or soup.select_one(".video-title")
        if h1 and len(h1.get_text(strip=True)) > len(title):
            title = h1.get_text(" ", strip=True)

        tags = [a.get_text(strip=True) for a in soup.select("a[href*='search?genre']") if a.get_text(strip=True)]
        return Detail(
            item=Item(provider=self.key, id=vid, title=title, cover=poster, url=url),
            description=(soup.select_one("meta[name='description']") or {}).get("content", "") if soup.select_one("meta[name='description']") else "",
            genres=sorted(set(tags))[:12],
            media=media,
            related=self._cards(html)[:12],
        )
