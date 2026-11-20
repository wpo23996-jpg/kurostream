"""Plain dataclasses used across providers and the API layer."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Media:
    url: str
    kind: str = "hls"          # "hls" | "mp4"
    quality: str = "auto"
    label: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Item:
    provider: str
    id: str
    title: str
    cover: str = ""
    url: str = ""
    duration: str = ""
    date: str = ""
    badges: list[str] = field(default_factory=list)
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Detail:
    item: Item
    description: str = ""
    actresses: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    maker: str = ""
    date: str = ""
    duration: str = ""
    media: list[Media] = field(default_factory=list)
    magnets: list[dict[str, Any]] = field(default_factory=list)
    related: list[Item] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["item"] = self.item.to_dict()
        d["media"] = [m.to_dict() for m in self.media]
        d["related"] = [i.to_dict() for i in self.related]
        return d


@dataclass
class SearchResult:
    items: list[Item]
    page: int = 1
    total_pages: int = 1
    total: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "page": self.page,
            "total_pages": self.total_pages,
            "total": self.total,
        }
