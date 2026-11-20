"""Orders, members and daily usage — the revenue side of the platform."""
from __future__ import annotations

import json
import os
import random
import secrets
import sqlite3
import string
import threading
import time
from dataclasses import dataclass
from typing import Any

from .membership import TIERS

DB_PATH = os.getenv("KS_DB", "kurostream.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    uid         TEXT PRIMARY KEY,
    tier        TEXT NOT NULL,
    expires_at  INTEGER NOT NULL,   -- unix ts, 0 = 永久
    updated_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_no    TEXT PRIMARY KEY,
    uid         TEXT NOT NULL,
    tier        TEXT NOT NULL,
    amount      REAL NOT NULL,
    channel     TEXT NOT NULL,
    status      TEXT NOT NULL,      -- pending | claimed | paid | cancelled | refunded
    created_at  INTEGER NOT NULL,
    paid_at     INTEGER,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_uid ON orders(uid);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE TABLE IF NOT EXISTS usage (
    uid   TEXT NOT NULL,
    day   TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (uid, day)
);
"""

FREE_DAILY = int(TIERS["free"]["daily"])


@dataclass
class Member:
    uid: str
    tier: str
    expires_at: int
    active: bool

    @property
    def label(self) -> str:
        return TIERS.get(self.tier, TIERS["free"])["name"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "tier": self.tier if self.active else "free",
            "label": self.label if self.active else "游客",
            "expires_at": self.expires_at if self.active else 0,
            "expires_text": _fmt_ts(self.expires_at) if self.active and self.expires_at else ("永久" if self.active else "—"),
            "active": self.active,
        }


def _fmt_ts(ts: int) -> str:
    if not ts:
        return "永久"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _order_no() -> str:
    stamp = time.strftime("%y%m%d%H%M%S")
    tail = "".join(random.choices(string.digits, k=5))
    return f"KS{stamp}{tail}"


class Store:
    _instance: "Store | None" = None

    def __init__(self, path: str = DB_PATH) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL lets several workers/sessions read while one writes
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @classmethod
    def get(cls) -> "Store":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------ members
    def member(self, uid: str) -> Member:
        with self.lock:
            row = self.conn.execute(
                "SELECT tier, expires_at FROM members WHERE uid=?", (uid,)
            ).fetchone()
        if not row:
            return Member(uid, "free", 0, False)
        tier, expires = row["tier"], row["expires_at"]
        active = tier in TIERS and tier != "free" and (expires == 0 or expires > time.time())
        return Member(uid, tier if active else "free", expires if active else 0, active)

    def grant(self, uid: str, tier: str, *, days: int | None = None) -> Member:
        """Extend (not overwrite) the membership. Lifetime wins permanently."""
        spec = TIERS.get(tier)
        if not spec:
            raise ValueError(f"unknown tier {tier}")
        now = int(time.time())
        current = self.member(uid)

        if tier == "lifetime":
            expires = 0
        else:
            span = (days if days is not None else spec["days"]) * 86400
            base = current.expires_at if (current.active and current.expires_at) else now
            expires = max(base, now) + span

        with self.lock:
            self.conn.execute(
                "INSERT INTO members (uid, tier, expires_at, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(uid) DO UPDATE SET tier=excluded.tier, expires_at=excluded.expires_at, "
                "updated_at=excluded.updated_at",
                (uid, tier, expires, now),
            )
            self.conn.commit()
        return self.member(uid)

    # ------------------------------------------------------------------- orders
    def create_order(self, uid: str, tier: str, channel: str, amount: float | None = None,
                     note: str = "") -> dict[str, Any]:
        spec = TIERS.get(tier)
        if not spec or tier == "free":
            raise ValueError(f"unknown tier {tier}")
        price = spec["price"] if amount is None else amount
        no = _order_no()
        now = int(time.time())
        with self.lock:
            self.conn.execute(
                "INSERT INTO orders (order_no, uid, tier, amount, channel, status, created_at, note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (no, uid, tier, price, channel, "pending", now, note),
            )
            self.conn.commit()
        return self.order(no)

    def order(self, no: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM orders WHERE order_no=?", (no,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tier_name"] = TIERS.get(d["tier"], {}).get("name", d["tier"])
        d["created_text"] = _fmt_ts(d["created_at"])
        d["paid_text"] = _fmt_ts(d["paid_at"]) if d.get("paid_at") else ""
        return d

    def orders_of(self, uid: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM orders WHERE uid=? ORDER BY created_at DESC LIMIT ?", (uid, limit)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tier_name"] = TIERS.get(d["tier"], {}).get("name", d["tier"])
            d["created_text"] = _fmt_ts(d["created_at"])
            out.append(d)
        return out

    def set_status(self, no: str, status: str) -> dict[str, Any] | None:
        with self.lock:
            self.conn.execute("UPDATE orders SET status=? WHERE order_no=?", (status, no))
            self.conn.commit()
        return self.order(no)

    def mark_paid(self, no: str) -> dict[str, Any]:
        order = self.order(no)
        if not order:
            raise ValueError("order not found")
        if order["status"] == "paid":
            return order
        now = int(time.time())
        with self.lock:
            self.conn.execute(
                "UPDATE orders SET status='paid', paid_at=? WHERE order_no=?", (now, no)
            )
            self.conn.commit()
        self.grant(order["uid"], order["tier"])
        return self.order(no) or order

    # -------------------------------------------------------------------- usage
    def bump_usage(self, uid: str, limit: int = FREE_DAILY) -> tuple[bool, int]:
        """Consume one view. Returns (allowed, used_today)."""
        day = time.strftime("%Y-%m-%d")
        with self.lock:
            row = self.conn.execute(
                "SELECT count FROM usage WHERE uid=? AND day=?", (uid, day)
            ).fetchone()
            used = row["count"] if row else 0
            if limit and used >= limit:
                return False, used
            used += 1
            self.conn.execute(
                "INSERT INTO usage (uid, day, count) VALUES (?,?,?) "
                "ON CONFLICT(uid, day) DO UPDATE SET count=excluded.count",
                (uid, day, used),
            )
            self.conn.commit()
        return True, used

    def usage_today(self, uid: str) -> int:
        day = time.strftime("%Y-%m-%d")
        with self.lock:
            row = self.conn.execute(
                "SELECT count FROM usage WHERE uid=? AND day=?", (uid, day)
            ).fetchone()
        return row["count"] if row else 0

    def stats(self) -> dict[str, Any]:
        with self.lock:
            paid = self.conn.execute("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM orders WHERE status='paid'").fetchone()
            members = self.conn.execute("SELECT COUNT(*) c FROM members").fetchone()
            pending = self.conn.execute("SELECT COUNT(*) c FROM orders WHERE status IN ('pending','claimed')").fetchone()
        return {
            "paid_orders": paid["c"],
            "revenue": round(paid["s"], 2),
            "members": members["c"],
            "pending_orders": pending["c"],
        }


def new_uid() -> str:
    return secrets.token_hex(8)


__all__ = ["Store", "Member", "new_uid", "FREE_DAILY", "json"]
