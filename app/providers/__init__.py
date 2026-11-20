"""Provider registry."""
from __future__ import annotations

import logging

from .base import BaseProvider, ProviderError
from .avple import AvpleProvider
from .eporner import EpornerProvider
from .hanime1 import Hanime1Provider
from .huangguo import HuangguoProvider
from .jable import JableProvider
from .javbus import JavbusProvider
from .javdb import JavdbProvider
from .missav import MissavProvider
from .supjav import SupjavProvider

log = logging.getLogger("kurostream.registry")

CLASSES = (
    MissavProvider,
    JableProvider,
    AvpleProvider,
    Hanime1Provider,
    HuangguoProvider,
    EpornerProvider,
    JavbusProvider,
    JavdbProvider,
    SupjavProvider,
)

_instances: dict[str, BaseProvider] = {}


def get(key: str) -> BaseProvider:
    if key not in _instances:
        cls = next((c for c in CLASSES if c.key == key), None)
        if cls is None:
            raise ProviderError(f"unknown provider: {key}")
        log.info("init provider %s", key)
        _instances[key] = cls()
    return _instances[key]


def get_preferred(keys: list[str] | None = None) -> list[BaseProvider]:
    if not keys:
        return [get(c.key) for c in CLASSES]
    out = []
    for k in keys:
        try:
            out.append(get(k))
        except ProviderError:
            log.warning("skip unknown provider %s", k)
    return out


def list_info() -> list[dict]:
    return [c.info() for c in CLASSES]


def all_hosts() -> tuple[str, ...]:
    hosts: list[str] = []
    for c in CLASSES:
        hosts.extend(c.hosts)
    return tuple(dict.fromkeys(hosts))
