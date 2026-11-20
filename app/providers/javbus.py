"""JavBus — metadata + magnet links (no embedded player)."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, SearchResult
from .base import BaseProvider

log = logging.getLogger("javhub.javbus")

CODE_RE = re.compile(r"/(?:[a-zA-Z]{2}/)?([A-Z0-9]+-\d+|[A-Z]+-\d+)$")


class JavbusProvider(BaseProvider):
    key = "javbus"
    label = "影片资料"
    lang = "zh"
    kinds = ("search", "browse", "detail")
    hosts = ("javbus.com", "cdn.javbus.com")
    notes = "影片资料库：番号、演员、标签、下载链接。"

    base = "https://www.javbus.com"

    def __init__(self) -> None:
        super().__init__()
        self.http.base = self.base
        self.http.default_headers["Cookie"] = "existmag=all; age=verified; dv=1"

    def _cards(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Item] = []
        seen: set[str] = set()
        for box in soup.select("a.movie-box"):
            href = box.get("href", "")
            m = CODE_RE.search(href.rstrip("/"))
            if not m:
                continue
            code = m.group(1).upper()
            if code in seen:
                continue
            seen.add(code)
            img = box.select_one("img")
            date = box.select_one("date")
            info = box.select_one("div.photo-info")
            title = (img.get("title") if img else "") or (info.get_text(" ", strip=True) if info else code)
            cover = ""
            if img:
                cover = img.get("src", "") or ""
                if cover.startswith("//"):
                    cover = "https:" + cover
                elif cover.startswith("/"):
                    cover = self.base + cover
            out.append(
                Item(
                    provider=self.key,
                    id=code,
                    title=f"{code} {title}".strip(),
                    cover=cover,
                    url=href,
                    date=date.get_text(strip=True) if date else "",
                )
            )
        return out

    def search(self, query: str, page: int = 1) -> SearchResult:
        url = f"{self.base}/search/{quote(query, safe='')}"
        html = self.http.get(url, params={"page": page} if page > 1 else None).text
        items = self._cards(html)
        pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
        return SearchResult(items=items, page=page, total_pages=max(pages) if pages else 1)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        route = {"new": "", "trending": "/uncensored", "chinese": "/chinese"}.get(sort, "")
        for r in dict.fromkeys([route, ""]):
            try:
                html = self.http.get(f"{self.base}{r}", params={"page": page} if page > 1 else None).text
                items = self._cards(html)
                if items:
                    return SearchResult(items=items, page=page, total_pages=self.pages_of(html))
            except Exception as exc:  # noqa: BLE001
                log.debug("javbus browse %r failed: %s", r, exc)
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        url = f"{self.base}/{vid.upper()}"
        html = self.http.get(url).text
        soup = BeautifulSoup(html, "lxml")

        title_node = soup.select_one("h3") or soup.select_one("title")
        title = title_node.get_text(" ", strip=True) if title_node else vid

        magnets = []
        for a in soup.select("a[href^='magnet:']"):
            magnets.append({"name": a.get_text(" ", strip=True) or vid, "magnet": a["href"], "size_bytes": None})

        genres = [a.get_text(strip=True) for a in soup.select("span.genre a") if a.get_text(strip=True)]
        actresses = [a.get_text(strip=True) for a in soup.select("div.star-name a") if a.get_text(strip=True)]

        meta: dict[str, str] = {}
        for item in soup.select("div.movie-info p") + soup.select("div.info p"):
            text = item.get_text(" ", strip=True)
            if ":" in text:
                k, v = text.split(":", 1)
                meta[k.strip()] = v.strip()

        date = meta.get("發行日期") or meta.get("发行日期") or meta.get("配信開始日", "")
        cover_node = soup.select_one("a.bigImage img") or soup.select_one("img.bigImage")
        cover = ""
        if cover_node:
            cover = cover_node.get("src", "") or ""
            if cover.startswith("//"):
                cover = "https:" + cover
            elif cover.startswith("/"):
                cover = self.base + cover
        return Detail(
            item=Item(provider=self.key, id=vid.upper(), title=title, cover=cover, url=url, date=date),
            actresses=actresses,
            genres=genres[:12],
            maker=meta.get("製作商") or meta.get("发行商", ""),
            date=date,
            duration=meta.get("長度", "") or meta.get("时长", ""),
            media=[],
            magnets=magnets,
            meta=meta,
        )
