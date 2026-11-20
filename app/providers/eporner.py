"""Eporner — clean public JSON search API (no HTML scraping needed for listings)."""
from __future__ import annotations

from urllib.parse import quote

from ..schemas import Detail, Item, Media, SearchResult
from .base import BaseProvider, ProviderError

ORDERS = {"new": "latest", "trending": "top-weekly", "top": "top-rated", "month": "top-monthly"}


class EpornerProvider(BaseProvider):
    key = "eporner"
    label = "欧美专区"
    lang = "en"
    kinds = ("search", "browse", "detail")
    hosts = ("eporner.com", "static-ca-cdn.eporner.com", "static.eporner.com", "eprld.com")
    notes = "欧美资源索引。"

    base = "https://www.eporner.com"
    api = "https://www.eporner.com/api/v2/video"

    def __init__(self) -> None:
        super().__init__()
        self.http.base = self.base

    def _parse(self, payload: dict, page: int) -> SearchResult:
        items: list[Item] = []
        for v in payload.get("videos", []):
            thumb = (v.get("default_thumb") or {}).get("src", "") or (v.get("thumbs") or [{}])[0].get("src", "")
            items.append(
                Item(
                    provider=self.key,
                    id=v.get("id", ""),
                    title=v.get("title", ""),
                    cover=thumb,
                    url=v.get("url", ""),
                    duration=v.get("length_min", ""),
                    date=(v.get("added") or "").split(" ")[0],
                    preview=v.get("embed", ""),
                )
            )
        return SearchResult(
            items=items,
            page=page,
            total_pages=int(payload.get("total_pages", 1) or 1),
            total=int(payload.get("total_count", 0) or 0),
        )

    def search(self, query: str, page: int = 1) -> SearchResult:
        payload = self.http.get(
            f"{self.api}/search/",
            params={
                "query": query,
                "per_page": 24,
                "page": page,
                "thumbsize": "big",
                "order": "top-weekly",
                "format": "json",
            },
        ).json()
        return self._parse(payload, page)

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        payload = self.http.get(
            f"{self.api}/search/",
            params={
                "query": "japanese",
                "per_page": 24,
                "page": page,
                "thumbsize": "big",
                "order": ORDERS.get(sort, "latest"),
                "format": "json",
            },
        ).json()
        return self._parse(payload, page)

    def detail(self, vid: str) -> Detail:
        # the v2 API only exposes search; fetch the page for title, then hand over the original link
        page_url = f"{self.base}/video-{vid}/"
        html = self.http.get(page_url, allow_redirects=True).text
        if "Age verification" in html[:2000]:
            raise ProviderError("eporner: age gate blocks direct access, open the original page")
        import re

        title_m = re.search(r"<title>(.*?)</title>", html, re.S)
        title = title_m.group(1).strip() if title_m else vid
        cover_m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        cover = cover_m.group(1) if cover_m else ""
        return Detail(
            item=Item(provider=self.key, id=vid, title=title, cover=cover, url=page_url),
            description="该条目暂未接入在线播放。",
            media=[],
            meta={"original_url": page_url},
        )
