"""MissAV (missav.ws / missav123.com / missav.ai) — HLS via packed player block."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..schemas import Detail, Item, Media, SearchResult
from . import _packer
from .base import BaseProvider, ProviderError

log = logging.getLogger("kurostream.missav")

CARD_HREF = re.compile(r"^https?://[^/]+/(?:dm\d+/)?[a-z]{2}(?:-[A-Za-z]+)?/([^/?#]+)$")
FAMILY = re.compile(r"-(?:chinese-subtitle|english-subtitle|uncensored-leak)$")
SORTS = {"new": "new", "trending": "today-hot", "weekly": "weekly-hot", "chinese": "chinese-subtitle"}


class MissavProvider(BaseProvider):
    key = "missav"
    label = "日本高清"
    lang = "zh"
    kinds = ("search", "browse", "detail", "media")
    hosts = ("surrit.com", "fourhoi.com", "missav.ws", "missav123.com", "missav.ai")
    notes = "高清片库，支持中文字幕/无码/新片分区。"

    domains = ("https://missav.ws", "https://missav123.com", "https://missav.ai")
    locale = "cn"

    def __init__(self) -> None:
        super().__init__()
        self._domain_idx = 0

    # ------------------------------------------------------------------ plumbing
    @property
    def base(self) -> str:
        return self.domains[self._domain_idx]

    def _fetch(self, path: str, *, referer: str = "") -> tuple[str, str]:
        last: Exception | None = None
        for attempt in range(len(self.domains) + 1):
            url = f"{self.base}{path}"
            try:
                resp = self.http.get(
                    url,
                    referer=referer or f"{self.base}/{self.locale}",
                    retries=2,
                )
                return resp.text, resp.url
            except Exception as exc:  # noqa: BLE001 - rotate mirrors
                last = exc
                self._domain_idx = (self._domain_idx + 1) % len(self.domains)
                log.warning("missav mirror fail, rotating to %s: %s", self.base, exc)
        raise ProviderError(f"missav unreachable: {last}")

    # ------------------------------------------------------------------- parsing
    @staticmethod
    def _parse_cards(html: str) -> list[Item]:
        soup = BeautifulSoup(html, "lxml")
        out: list[Item] = []
        seen: set[str] = set()
        for card in soup.select("div.thumbnail.group"):
            anchor = next((a for a in card.select("a[href]") if a.get("href", "").startswith("http")), None)
            if anchor is None:
                continue
            href = anchor["href"]
            m = CARD_HREF.match(href.split("?")[0].split("#")[0])
            if not m or m.group(1) in seen:
                continue
            dvd = m.group(1)
            seen.add(dvd)
            img = card.select_one("img[data-src], img[src^='http']")
            video = card.select_one("video[data-src]")
            title_node = card.select_one("div.my-2 a") or card.select_one("div.truncate a")
            dur = card.select_one("span.absolute.bottom-1.right-1")
            badges = [b.get_text(strip=True) for b in card.select("span.absolute.bottom-1.left-1") if b.get_text(strip=True)]
            out.append(
                Item(
                    provider="missav",
                    id=dvd,
                    title=(title_node.get_text(" ", strip=True) if title_node else dvd),
                    cover=(img.get("data-src") or img.get("src") or "") if img else "",
                    preview=video.get("data-src", "") if video else "",
                    url=href,
                    duration=dur.get_text(strip=True) if dur else "",
                    badges=badges,
                )
            )
        return out

    @staticmethod
    def _last_page(html: str) -> int:
        pages = [int(n) for n in re.findall(r"[?&]page=(\d+)", html)]
        return max(pages) if pages else 1

    # ----------------------------------------------------------------- operations
    def search(self, query: str, page: int = 1) -> SearchResult:
        path = f"/{self.locale}/search/{quote(query, safe='')}"
        if page > 1:
            path += f"?page={page}"
        html, _ = self._fetch(path)
        items = self._parse_cards(html)
        if not items:
            raise ProviderError("missav: empty result page")
        return SearchResult(items=items, page=page, total_pages=self._last_page(html))

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        route = SORTS.get(sort, sort if sort in SORTS.values() else "new")
        suffix = f"?page={page}" if page > 1 else ""
        for path in (f"/{self.locale}/{route}{suffix}", f"/{self.locale}{suffix}"):
            try:
                html, url = self._fetch(path)
                items = self._parse_cards(html)
                if items:
                    return SearchResult(items=items, page=page, total_pages=self._last_page(html))
            except Exception as exc:  # noqa: BLE001 - fall back to the home feed
                log.debug("missav browse %s failed: %s", path, exc)
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        dvd = FAMILY.sub("", vid.strip().lower()) if vid.endswith(("-uncensored-leak", "-chinese-subtitle", "-english-subtitle")) else vid.strip().lower()
        path = f"/{self.locale}/{quote(dvd, safe='')}"
        html, url = self._fetch(path)
        soup = BeautifulSoup(html, "lxml")

        h1 = soup.select_one("h1")
        title = h1.get_text(" ", strip=True) if h1 else dvd.upper()
        meta = self._meta_table(soup)

        media = [
            Media(url=s["url"], kind="hls", quality=s["quality"], label=f"HLS {s['quality']}")
            for s in _packer.m3u8_urls(html)
        ]
        if not media:
            raise ProviderError("missav: this video has no playable source (VIP-only?)")

        magnets = []
        for a in soup.select("a[href^='magnet:']"):
            size = re.search(r"[?&]size=(\d+)", a["href"])
            magnets.append(
                {
                    "name": a.get_text(" ", strip=True),
                    "magnet": a["href"],
                    "size_bytes": int(size.group(1)) if size else None,
                }
            )

        actresses = meta.get("actresses", [])
        if isinstance(actresses, str):
            actresses = [actresses]

        item = Item(
            provider="missav",
            id=dvd,
            title=title,
            cover=meta.get("_cover", ""),
            url=url,
            duration=meta.get("duration", ""),
            date=meta.get("release_date", ""),
            badges=[],
        )
        return Detail(
            item=item,
            description=meta.get("_desc", ""),
            actresses=[a.split(" (")[0] for a in actresses],
            genres=meta.get("genres", []) if isinstance(meta.get("genres"), list) else [],
            maker=";".join(meta["maker"]) if isinstance(meta.get("maker"), list) else str(meta.get("maker", "") or ""),
            date=str(meta.get("release_date", "")),
            duration=str(meta.get("duration", "")),
            media=media,
            magnets=magnets,
            related=self._parse_cards(html)[:12],
            meta={k: v for k, v in meta.items() if not k.startswith("_")},
        )

    # --------------------------------------------------------------------- utils
    @staticmethod
    def _meta_table(soup) -> dict:
        from ._labels import LABELS

        out: dict = {}
        for div in soup.select("div.text-secondary"):
            spans = div.find_all("span", recursive=False)
            if not spans:
                continue
            label = spans[0].get_text(strip=True).rstrip(":：").strip().lower()
            key = LABELS.get(label)
            if not key:
                continue
            links = [a.get_text(" ", strip=True) for a in div.find_all("a") if a.get_text(strip=True)]
            if links:
                out[key] = links
                continue
            t = div.find("time")
            if t:
                out[key] = t.get("datetime", "") or t.get_text(strip=True)
                continue
            raw = div.get_text(" ", strip=True).replace(spans[0].get_text(strip=True), "", 1).strip()
            out[key] = raw
        if isinstance(out.get("release_date"), str) and "T" in out["release_date"]:
            out["release_date"] = out["release_date"].split("T")[0]
        poster = soup.select_one("video.player[data-poster]")
        img = soup.select_one("img[data-src*='cover']")
        out["_cover"] = (poster.get("data-poster", "") if poster else "") or (img.get("data-src", "") if img else "")
        og = soup.select_one("meta[property='og:description']")
        out["_desc"] = og.get("content", "") if og else ""
        return out
