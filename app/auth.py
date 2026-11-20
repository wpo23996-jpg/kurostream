"""账号系统：注册 / 登录 / 会话 token。

密码用 PBKDF2-SHA256（标准库，无需额外依赖）。
用户 ID 在会员表里记为 "user:<id>"，和游客的设备 uid 共存。
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time

DB_PATH = os.getenv("KS_DB", "kurostream.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT UNIQUE NOT NULL,
    pass_hash   TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

SESSION_DAYS = int(os.getenv("KS_SESSION_DAYS", "90"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=5000")
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


# ------------------------------------------------------------------ password
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------- users
def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def create_user(email: str, password: str) -> dict:
    email = normalize_email(email)
    if not EMAIL_RE.match(email):
        raise ValueError("邮箱格式不正确")
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")

    db = _db()
    with _lock:
        exists = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            raise ValueError("这个邮箱已经注册过了")
        cur = db.execute(
            "INSERT INTO users (email, pass_hash, created_at) VALUES (?,?,?)",
            (email, hash_password(password), int(time.time())),
        )
        db.commit()
        uid = cur.lastrowid
    return {"id": uid, "email": email, "uid": f"user:{uid}"}


def authenticate(email: str, password: str) -> dict:
    email = normalize_email(email)
    db = _db()
    with _lock:
        row = db.execute("SELECT id, email, pass_hash FROM users WHERE email=?", (email,)).fetchone()
    if not row or not verify_password(password, row["pass_hash"]):
        raise ValueError("邮箱或密码错误")
    return {"id": row["id"], "email": row["email"], "uid": f"user:{row['id']}"}


def get_user(uid: str) -> dict | None:
    if not uid.startswith("user:"):
        return None
    try:
        uid_int = int(uid.split(":", 1)[1])
    except (ValueError, IndexError):
        return None
    db = _db()
    with _lock:
        row = db.execute("SELECT id, email, created_at FROM users WHERE id=?", (uid_int,)).fetchone()
    return dict(row) if row else None


def set_password(email: str, password: str) -> bool:
    email = normalize_email(email)
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")
    db = _db()
    with _lock:
        cur = db.execute("UPDATE users SET pass_hash=? WHERE email=?", (hash_password(password), email))
        db.commit()
        return cur.rowcount > 0


# ------------------------------------------------------------------ sessions
def issue_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db = _db()
    with _lock:
        db.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user_id, now, now + SESSION_DAYS * 86400),
        )
        db.commit()
    return token


def user_of_token(token: str) -> dict | None:
    if not token:
        return None
    db = _db()
    with _lock:
        row = db.execute(
            "SELECT s.user_id, s.expires_at, u.email FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token=?",
            (token,),
        ).fetchone()
    if not row:
        return None
    if row["expires_at"] < time.time():
        revoke(token)
        return None
    return {"id": row["user_id"], "email": row["email"], "uid": f"user:{row['user_id']}"}


def revoke(token: str) -> None:
    db = _db()
    with _lock:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        db.commit()


def stats() -> dict:
    db = _db()
    with _lock:
        users = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        sessions = db.execute("SELECT COUNT(*) c FROM sessions WHERE expires_at > ?", (time.time(),)).fetchone()["c"]
    return {"users": users, "sessions": sessions}
