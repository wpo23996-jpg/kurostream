"""Tiny TTL cache shared by API handlers."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    def __init__(self, ttl: int = 300, maxsize: int = 2048) -> None:
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._data.get(key)
            if not hit:
                return None
            expires, value = hit
            if expires < time.time():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        with self._lock:
            if len(self._data) >= self.maxsize:
                now = time.time()
                self._data = {k: v for k, v in self._data.items() if v[0] > now}
                if len(self._data) >= self.maxsize:
                    self._data.pop(next(iter(self._data)), None)
            self._data[key] = (time.time() + (ttl or self.ttl), value)

    def get_or(self, key: str, factory: Callable[[], Any], ttl: int | None = None) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


cache = TTLCache()
