"""Provider contract + registry."""
from __future__ import annotations

import logging
import re
from typing import ClassVar

from ..http_client import Http
from ..schemas import Detail, Item, SearchResult

log = logging.getLogger("kurostream.provider")

PAGE_PATTERNS = (
    re.compile(r"[?&]page=(\d+)"),
    re.compile(r"/page/(\d+)/?"),
    re.compile(r'data-pages="(\d+)"'),
    re.compile(r'data-max-page="(\d+)"'),
    re.compile(r"[?&]from=(\d+)"),
)


def parse_last_page(html: str) -> int:
    """从列表页 HTML 抠出最大页码，抠不到返回 1。"""
    best = 1
    for rx in PAGE_PATTERNS:
        for m in rx.finditer(html or ""):
            try:
                n = int(m.group(1))
            except (ValueError, IndexError):
                continue
            if 1 < n < 200000:
                best = max(best, n)
    return best


class ProviderError(RuntimeError):
    pass


class BaseProvider:
    key: ClassVar[str] = ""
    label: ClassVar[str] = ""
    lang: ClassVar[str] = "en"
    kinds: ClassVar[tuple[str, ...]] = ("search", "browse", "detail")  # capabilities
    hosts: ClassVar[tuple[str, ...]] = ()      # media hosts for the proxy allow-list
    notes: ClassVar[str] = ""

    def __init__(self) -> None:
        self.http = Http()

    # ------------------------------------------------------------------ to implement
    def search(self, query: str, page: int = 1) -> SearchResult:
        raise NotImplementedError

    def browse(self, page: int = 1, sort: str = "new", **kwargs) -> SearchResult:
        """Generic landing feed. Defaults to an empty successful result."""
        return SearchResult(items=[], page=page, total_pages=1)

    def detail(self, vid: str) -> Detail:
        raise NotImplementedError

    def recommend(self, vid: str, n: int = 12) -> list[Item]:
        """Fallback recommendations: same code family first, then the channel feed."""
        prefix = vid.split("-")[0] if "-" in vid else vid
        try:
            res = self.search(prefix, 1)
            items = [i for i in res.items if i.id != vid]
            if items:
                return items[:n]
        except Exception:  # noqa: BLE001
            pass
        try:
            res = self.browse(1, "new")
            return [i for i in res.items if i.id != vid][:n]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ helpers
    def _item(self, **kwargs) -> Item:
        return Item(provider=self.key, **kwargs)

    @staticmethod
    def pages_of(html: str) -> int:
        return parse_last_page(html)

    @classmethod
    def info(cls) -> dict:
        return {
            "key": cls.key,
            "label": cls.label,
            "kinds": list(cls.kinds),
            "lang": cls.lang,
            "notes": cls.notes,
        }

    def close(self) -> None:
        self.http.close()
