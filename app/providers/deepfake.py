"""AI 换脸（DeepfakePorn.net，KVS 系）。

数据来源两条路：
  1. RSS  /rss/           → 12 条，秒回
  2. 分页 /latest-updates/{n}/ → 需要浏览器渲染（列表是 JS 拼的），走 FlareSolverr

详情页含 video_alt_url（完整 mp4）与 video_url（360p），都是直链，Range 可拖。
premium 条目只有 preview 片段，直接丢弃（保证"能看"）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, Media, SearchResult
from .base import BaseProvider, ProviderError

log = logging.getLogger("javhub.deepfake")

BASE = "https://www.deepfakeporn.net"
FLARE = os.getenv("KS_FLARESOLVERR", "").strip()
CACHE_TTL = 600

SLUG_SKIP = {"latest-updates", "most-popular", "categories", "login-required", "signup",
             "login", "rss", "actor", "tag", "search"}
RSS_CACHE: dict[str, tuple[float, str]] = {}


class DeepfakeProvider(BaseProvider):
    key = "deepfake"
    label = "AI换脸"
    lang = "zh"
    kinds = ("browse", "detail", "media")
    hosts = ("deepfakeporn.net", "anycdn.xyz")
    notes = "亚洲明星 AI 换脸视频，mp4 直链可直接拖动进度"

    base = BASE

    def __init__(self) -> None:
        super().__init__()
        self.http.base = BASE
        self.http.default_headers.update({"Accept-Language": "en-US,en;q=0.9"})

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _slug_from_url(url: str) -> str:
        path = url.split("?")[0].rstrip("/")
        return path.rsplit("/", 1)[-1]

    def _render(self, url: str) -> str:
        """用 FlareSolverr 渲染列表页（结果缓 10 分钟）。"""
        now = time.time()
        hit = RSS_CACHE.get(url)
        if hit and hit[0] > now:
            return hit[1]
        if not FLARE:
            raise ProviderError("deepfake: 列表需要 FlareSolverr，但未配置 KS_FLARESOLVERR")
        import urllib.request

        req = urllib.request.Request(
            FLARE,
            data=json.dumps({"cmd": "request.get", "url": url, "maxTimeout": 60000}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        if data.get("status") != "ok":
            raise ProviderError(f"flaresolverr: {data.get('message')}")
        html = (data.get("solution") or {}).get("response", "")
        RSS_CACHE[url] = (now + CACHE_TTL, html)
        return html

    def _from_rss(self) -> list[Item]:
        try:
            text = self.http.get(f"{BASE}/rss/").text
        except Exception:  # noqa: BLE001
            return []
        out: list[Item] = []
        for m in re.finditer(r"<item>(.*?)</item>", text, re.S):
            block = m.group(1)
            lm = re.search(r"<link>\s*(?:<!\[CDATA\[)?(https://[^\]<]+)", block)
            tm = re.search(r"<title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
            if not lm:
                continue
            url = lm.group(1).strip()
            slug = self._slug_from_url(url)
            if not slug or slug in SLUG_SKIP:
                continue
            title = re.sub(r"\s+", " ", tm.group(1)).strip() if tm else slug.replace("-", " ")
            out.append(Item(provider=self.key, id=slug, title=title, url=url))
        return out

    def _cards_from_html(self, html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Item] = []
        seen: set[str] = set()
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "deepfakeporn" not in href and not href.startswith("/"):
                continue
            slug = self._slug_from_url(urljoin(BASE + "/", href))
            if not slug or slug in SLUG_SKIP or len(slug) < 8 or "/" in slug:
                continue
            if slug in seen:
                continue
            title = a.get_text(" ", strip=True)
            img = a.select_one("img")
            if not title and img is not None:
                title = img.get("alt", "")
            if not title:
                continue
            seen.add(slug)
            cover = ""
            if img is not None:
                cover = img.get("data-src") or img.get("data-original") or img.get("src") or ""
                if cover.startswith("/"):
                    cover = BASE + cover
            out.append(
                Item(
                    provider=self.key,
                    id=slug,
                    title=title,
                    cover=cover,
                    url=f"{BASE}/{slug}/",
                )
            )
        return out

    # --------------------------------------------------------------- operations
    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        if page == 1:
            items = self._from_rss()
            if items:
                return SearchResult(items=items, page=page, total_pages=9999)
        route = {"new": "latest-updates", "trending": "most-popular"}.get(sort, "latest-updates")
        url = f"{BASE}/{route}/" if page <= 1 else f"{BASE}/{route}/{page}/"
        try:
            html = self._render(url)
        except Exception as exc:  # noqa: BLE001
            log.debug("deepfake browse %s failed: %s", url, exc)
            return SearchResult(items=[], page=page, total_pages=1)
        items = self._cards_from_html(html)
        if not items:
            return SearchResult(items=[], page=page, total_pages=1)
        return SearchResult(items=items, page=page, total_pages=9999)

    def search(self, query: str, page: int = 1) -> SearchResult:
        from urllib.parse import quote

        try:
            html = self._render(f"{BASE}/search/{quote(query, safe='')}/")
        except Exception:  # noqa: BLE001
            return SearchResult(items=[], page=page, total_pages=1)
        return SearchResult(items=self._cards_from_html(html), page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        slug = vid.strip("/").split("/")[-1]
        url = f"{BASE}/{slug}/"
        html = self.http.get(url).text
        soup = BeautifulSoup(html, "lxml")

        title_node = soup.select_one("h1")
        title = title_node.get_text(" ", strip=True) if title_node else slug.replace("-", " ")
        poster = soup.select_one("video[poster]")
        cover = poster.get("poster", "") if poster else ""

        media: list[Media] = []
        alt = None
        for pat in (r"video_alt_url\s*[:=]\s*['\"]([^'\"]+)", r"video_url\s*[:=]\s*['\"]([^'\"]+)"):
            m = re.search(pat, html)
            if m:
                alt = m.group(1).replace("\\/", "/")
                break
        if not alt:
            raise ProviderError("deepfake: 这条是付费预览，没有完整片源")

        media.append(Media(url=alt, kind="mp4", quality="full", label="完整版",
                           headers={"Referer": url}))
        m360 = re.search(r"video_url\s*[:=]\s*['\"]([^'\"]+)", html)
        if m360:
            u360 = m360.group(1).replace("\\/", "/")
            if u360 != alt:
                media.append(Media(url=u360, kind="mp4", quality="360p", label="360p",
                                   headers={"Referer": url}))

        desc = ""
        md = soup.select_one("meta[name='description']")
        if md:
            desc = md.get("content", "")

        return Detail(
            item=Item(provider=self.key, id=slug, title=title, cover=cover, url=url),
            description=desc,
            genres=["AI换脸"],
            media=media,
            related=[],
            meta={"source": "deepfakeporn.net"},
        )
