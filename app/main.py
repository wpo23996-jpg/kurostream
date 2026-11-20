"""FastAPI application: aggregated search, detail, and the media proxy."""
from __future__ import annotations

import copy
import hashlib
import os
import asyncio
import logging
from pathlib import Path
from typing import Any

from curl_cffi import requests as cr
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import auth, membership, orders, payments, providers
from .branding import internal_key, public_blurb, public_key, public_label
from .cache import cache
from .config import PUBLIC_BASE, SITE_NAME, SITE_TAGLINE, settings
from .proxy import b64d, b64e, host_allowed, proxy_url, rewrite_hls

ADMIN_TOKEN = os.getenv("KS_ADMIN_TOKEN", "").strip()
DEV_MODE = os.getenv("KS_DEV_MODE", "0") == "1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kurostream")

app = FastAPI(title="kurostream", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# --------------------------------------------------------------------------- utils
def uid_of(request: Request | None) -> str:
    """身份优先级：登录 token > 客户端 uid > IP 哈希。"""
    if request is not None:
        token = (request.headers.get("x-ks-token") or "").strip()
        if token:
            user = auth.user_of_token(token)
            if user:
                return user["uid"]
        raw = (request.headers.get("x-ks-uid") or "").strip()
        if 6 <= len(raw) <= 64 and all(c.isalnum() or c in "-_" for c in raw):
            return raw
        peer = request.client.host if request.client else "anon"
        return "ip-" + hashlib.sha1(peer.encode()).hexdigest()[:12]
    return "ip-anon"


def require_admin(request: Request) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(503, "后台未配置：请设置环境变量 KS_ADMIN_TOKEN")
    if request.headers.get("x-admin-token", "") != ADMIN_TOKEN:
        raise HTTPException(403, "管理员令牌无效")
def _referer_for(url: str) -> str:
    from urllib.parse import urlparse

    from .config import IMAGE_REFERERS

    host = (urlparse(url).hostname or "").lower()
    for suffix, ref in IMAGE_REFERERS.items():
        if host == suffix or host.endswith("." + suffix):
            return ref
    return ""


def _decorate(item: dict[str, Any]) -> dict[str, Any]:
    """Strip upstream identifiers: clients only see public catalogue data."""
    item["provider"] = public_key(item.get("provider", ""))
    cover = item.get("cover") or ""
    if cover and host_allowed(cover):
        ref = _referer_for(cover)
        # absolute when KS_PUBLIC_BASE is set (native shells), same-origin otherwise
        item["cover_proxy"] = f"{PUBLIC_BASE}/api/img?u={b64e(cover)}" + (f"&r={b64e(ref)}" if ref else "")
    else:
        item["cover_proxy"] = ""
    for field in ("cover", "url", "preview"):
        item.pop(field, None)
    return item

def _group(provider, page, items, total_pages=None, total=None, error=None) -> dict[str, Any]:
    return {
        "provider": public_key(provider.key),
        "label": public_label(provider.key),
        "items": [_decorate(i.to_dict()) for i in items],
        "page": page,
        "total_pages": total_pages or 1,
        "total": total,
        "error": error,
    }


def _fetch_text(url: str, referer: str) -> str:
    resp = cr.get(
        url,
        impersonate=settings.impersonate,
        timeout=30,
        headers={
            "User-Agent": settings.user_agent,
            "Referer": referer,
            "Accept": "*/*",
        },
    )
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, f"upstream {resp.status_code}")
    return resp.text


def _fetch_bytes(url: str, referer: str) -> tuple[bytes, str]:
    resp = cr.get(
        url,
        impersonate=settings.impersonate,
        timeout=30,
        headers={"User-Agent": settings.user_agent, "Referer": referer, "Accept": "image/*,*/*"},
    )
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, f"upstream {resp.status_code}")
    return resp.content, resp.headers.get("content-type", "application/octet-stream")


# ----------------------------------------------------------------------- API routes
@app.get("/api/health")
def health() -> dict[str, Any]:
    from .cf import solver as cf_solver

    return {
        "ok": True,
        "providers": len(providers.CLASSES),
        "version": os.getenv("KS_BUILD", "1.6.3"),
        "public_base": PUBLIC_BASE or None,
        "flare": cf_solver.enabled,
    }


@app.on_event("startup")
async def _warmup_cloudflare() -> None:
    """后台预热：串行把主要源过一遍挑战，避免首屏卡住、也避免并发压垮 FlareSolverr。"""
    from .cf import solver as cf_solver

    if not cf_solver.enabled:
        return

    async def warm() -> None:
        # 只预热最重的两个，其余按需解；FlareSolverr 一次只能跑一个，排队越久越容易超时
        for url in ("https://missav.ws/cn", "https://jable.tv/"):
            for attempt in range(2):
                try:
                    await asyncio.to_thread(cf_solver.get, url)
                    log.info("cf warmup ok: %s", url)
                    break
                except Exception as exc:  # noqa: BLE001
                    log.warning("cf warmup %s failed (try %d): %s", url, attempt + 1, exc)
                    await asyncio.sleep(5)
        log.info("cf warmup done, hosts=%s", cf_solver.cached_hosts())

    asyncio.create_task(warm())


@app.get("/api/providers")
def api_providers() -> dict[str, Any]:
    sections = [
        {
            "key": public_key(cls.key),
            "label": public_label(cls.key),
            "blurb": public_blurb(cls.key),
            "kinds": list(cls.kinds),
        }
        for cls in providers.CLASSES
    ]
    return {"site": SITE_NAME, "tagline": SITE_TAGLINE, "providers": sections}


@app.get("/api/search")
async def api_search(q: str, provider: str = "all", page: int = 1, sort: str = "new",
                     limit: int = 0) -> dict[str, Any]:
    if not q.strip():
        raise HTTPException(400, "empty query")
    keys = None if provider in ("", "all") else [internal_key(k) for k in provider.split(",") if k]
    pool = providers.get_preferred(keys)

    async def one(p):
        key = f"search:{p.key}:{q}:{page}"
        hit = cache.get(key)
        if hit is not None:
            return hit
        try:
            res = await asyncio.to_thread(p.search, q, page)
            items = res.items[:limit] if limit else res.items
            data = _group(p, page, items, res.total_pages, res.total)
        except Exception as exc:  # noqa: BLE001 - one broken source must not kill the page
            log.warning("search %s failed: %s", p.key, exc)
            data = _group(p, page, [], 1, None, f"{type(exc).__name__}: {exc}")
        if data["items"]:  # never cache an empty page — let the next request retry
            cache.set(key, data)
        return data

    groups = await asyncio.gather(*(one(p) for p in pool))
    return {"query": q, "page": page, "sort": sort, "groups": list(groups)}


@app.get("/api/browse")
async def api_browse(provider: str = "all", page: int = 1, sort: str = "new",
                     limit: int = 0) -> dict[str, Any]:
    keys = None if provider in ("", "all") else [internal_key(k) for k in provider.split(",") if k]
    pool = providers.get_preferred(keys)

    async def one(p):
        key = f"browse:{p.key}:{page}:{sort}"
        hit = cache.get(key)
        if hit is not None:
            data = dict(hit)
            if limit:
                data["items"] = data["items"][:limit]
            return data
        try:
            res = await asyncio.to_thread(p.browse, page, sort)
            data = _group(p, page, res.items, res.total_pages, res.total)
        except Exception as exc:  # noqa: BLE001
            log.warning("browse %s failed: %s", p.key, exc)
            data = _group(p, page, [], 1, None, f"{type(exc).__name__}: {exc}")
        if data["items"]:
            cache.set(key, data)
        if limit:
            data = dict(data)
            data["items"] = data["items"][:limit]
        return data

    groups = await asyncio.gather(*(one(p) for p in pool))
    return {"page": page, "sort": sort, "groups": list(groups)}


async def _detail_raw(real: str, vid: str) -> dict[str, Any]:
    """Parse once, cache the raw payload (still contains upstream URLs)."""
    key = f"raw:{real}:{vid}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    p = providers.get(real)
    try:
        detail = await asyncio.to_thread(p.detail, vid)
    except Exception as exc:  # noqa: BLE001
        log.warning("detail %s/%s failed: %s", real, vid, exc)
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc
    payload = detail.to_dict()
    cache.set(key, payload, ttl=600)
    return payload


@app.get("/api/detail")
async def api_detail(provider: str, id: str, request: Request, preview_tier: str = "") -> dict[str, Any]:
    real = internal_key(provider)
    p = providers.get(real)
    store = orders.Store.get()
    uid = uid_of(request)
    member = store.member(uid)

    owner = _is_owner(request)

    # membership is decided server-side only
    tier_key = "lifetime" if owner else (member.tier if member.active else "free")
    if DEV_MODE and preview_tier:
        tier_key = membership.get(preview_tier)["key"]

    quota = None
    if tier_key == "free" and not owner:
        allowed, used = store.bump_usage(uid, orders.FREE_DAILY)
        if not allowed:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "quota_exhausted",
                    "message": f"今日免费额度已用完（{used}/{orders.FREE_DAILY}），开通会员可无限观看",
                    "used": used,
                    "limit": orders.FREE_DAILY,
                },
            )
        quota = {"used": used, "limit": orders.FREE_DAILY}

    payload = copy.deepcopy(await _detail_raw(real, id))
    upstream_url = payload["item"].get("url", "")

    if not payload.get("related"):
        try:
            rec = await asyncio.to_thread(p.recommend, id, 12)
            payload["related"] = [x.to_dict() for x in rec]
        except Exception as exc:  # noqa: BLE001 - recommendations are optional
            log.debug("recommend %s/%s failed: %s", real, id, exc)

    gated: list[dict[str, Any]] = []
    for m in membership.filter_media(payload["media"], tier_key):
        ref = (m.get("headers") or {}).get("Referer") or upstream_url or m.get("url", "")
        m["play"] = proxy_url(m.get("url", ""), ref)
        m.pop("url", None)
        m.pop("headers", None)
        gated.append(m)
    payload["media"] = gated

    _decorate(payload["item"])
    payload["related"] = [_decorate(r) for r in payload.get("related", [])]
    payload["provider"] = public_key(real)
    payload["provider_label"] = public_label(real)
    payload["tier"] = tier_key
    payload["max_height"] = membership.max_height(tier_key)
    payload["member"] = member.to_dict()
    payload["owner"] = owner
    payload["quota"] = quota
    payload["meta"] = {
        k: v
        for k, v in (payload.get("meta") or {}).items()
        if k not in ("original_url", "note", "url")
    } if isinstance(payload.get("meta"), dict) else {}
    return payload


# ------------------------------------------------------------------ account / pay
# ------------------------------------------------------------------ account / pay
@app.post("/api/register")
def api_register(payload: dict = Body(...)) -> dict[str, Any]:
    email = str(payload.get("email", ""))
    password = str(payload.get("password", ""))
    try:
        user = auth.create_user(email, password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    token = auth.issue_token(user["id"])
    member = orders.Store.get().member(user["uid"])
    return {"ok": True, "token": token, "user": {"email": user["email"], "uid": user["uid"]},
            "member": member.to_dict()}


@app.post("/api/login")
def api_login(payload: dict = Body(...)) -> dict[str, Any]:
    email = str(payload.get("email", ""))
    password = str(payload.get("password", ""))
    try:
        user = auth.authenticate(email, password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    token = auth.issue_token(user["id"])
    member = orders.Store.get().member(user["uid"])
    return {"ok": True, "token": token, "user": {"email": user["email"], "uid": user["uid"]},
            "member": member.to_dict()}


@app.post("/api/logout")
def api_logout(request: Request) -> dict[str, Any]:
    token = (request.headers.get("x-ks-token") or "").strip()
    if token:
        auth.revoke(token)
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request) -> dict[str, Any]:
    store = orders.Store.get()
    uid = uid_of(request)
    member = store.member(uid)
    owner = _is_owner(request)
    user = auth.get_user(uid)
    base = member.to_dict()
    if owner:
        base = {"uid": uid, "tier": "lifetime", "label": "店主", "expires_at": 0,
                "expires_text": "永久", "active": True}
    return {
        **base,
        "uid": uid,
        "owner": owner,
        "logged_in": bool(user),
        "email": (user or {}).get("email", ""),
        "quota": {"used": store.usage_today(uid), "limit": orders.FREE_DAILY},
        "orders": store.orders_of(uid, 5),
    }


@app.get("/api/paychannels")
def api_paychannels() -> dict[str, Any]:
    return {"channels": payments.channels(), "default": payments.default_channel()}


@app.post("/api/order")
def api_create_order(payload: dict = Body(...), request: Request = None) -> dict[str, Any]:
    store = orders.Store.get()
    uid = uid_of(request)
    tier = str(payload.get("tier", ""))
    channel = str(payload.get("channel") or payments.default_channel())
    if tier not in membership.TIERS or tier in ("free", "trial"):
        raise HTTPException(400, "无效的套餐")
    if channel not in [c["key"] for c in payments.channels()]:
        raise HTTPException(400, "无效的支付方式")
    try:
        order = store.create_order(uid, tier, channel)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"order": order, "pay": payments.instructions(channel, order)}


@app.get("/api/order/{no}")
def api_get_order(no: str, request: Request) -> dict[str, Any]:
    store = orders.Store.get()
    order = store.order(no)
    if not order:
        raise HTTPException(404, "订单不存在")
    if order["uid"] != uid_of(request) and not _is_admin(request):
        raise HTTPException(403, "无权查看该订单")
    return {"order": order, "pay": payments.instructions(order["channel"], order)}


@app.post("/api/order/{no}/claim")
def api_claim_order(no: str, request: Request) -> dict[str, Any]:
    """Customer says "I paid" — moves the order to the manual-review queue."""
    store = orders.Store.get()
    order = store.order(no)
    if not order:
        raise HTTPException(404, "订单不存在")
    if order["uid"] != uid_of(request):
        raise HTTPException(403, "无权操作该订单")
    if order["status"] in ("paid", "refunded"):
        return {"order": order}
    order = store.set_status(no, "claimed") or order
    return {"order": order, "message": "已提交，客服确认后自动开通（通常 5 分钟内）"}


def _is_admin(request: Request | None) -> bool:
    return bool(ADMIN_TOKEN) and request is not None and request.headers.get("x-admin-token", "") == ADMIN_TOKEN


def _is_owner(request: Request | None) -> bool:
    """站主请求：带正确管理令牌的访客，等同终身会员、不计额度、不过滤画质。"""
    return _is_admin(request)


@app.post("/api/admin/order/{no}/confirm")
def api_admin_confirm(no: str, request: Request) -> dict[str, Any]:
    require_admin(request)
    store = orders.Store.get()
    try:
        order = store.mark_paid(no)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    member = store.member(order["uid"])
    return {"order": order, "member": member.to_dict()}


@app.get("/api/admin/stats")
def api_admin_stats(request: Request) -> dict[str, Any]:
    require_admin(request)
    store = orders.Store.get()
    return store.stats()


@app.get("/api/plans")
def api_plans() -> dict[str, Any]:
    data = membership.public_plans()
    data["channels"] = payments.channels()
    data["default_channel"] = payments.default_channel()
    return data


@app.get("/api/media/hls")
async def media_hls(u: str, r: str = "") -> Response:
    try:
        url = b64d(u)
        ref = b64d(r) if r else url
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "bad base64") from exc
    if not host_allowed(url):
        raise HTTPException(403, "host not allowed")
    text = await asyncio.to_thread(_fetch_text, url, ref)
    return Response(
        rewrite_hls(text, url, ref),
        media_type="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
    )


@app.get("/api/media/raw")
def media_raw(u: str, r: str = "", request: Request = None):
    from . import segcache

    try:
        url = b64d(u)
        ref = b64d(r) if r else url
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "bad base64") from exc
    if not host_allowed(url):
        raise HTTPException(403, "host not allowed")

    rng = request.headers.get("range") if request else None

    # 无 Range 的分片请求：先查磁盘缓存，命中直接返回（拖动进度秒开）
    if not rng:
        hit = segcache.get(url)
        if hit is not None:
            return Response(
                hit,
                media_type="application/octet-stream",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Cache-Control": "public, max-age=86400",
                    "X-Seg-Cache": "hit",
                },
            )

    sess = cr.Session(impersonate=settings.impersonate)
    headers = {"User-Agent": settings.user_agent, "Referer": ref, "Accept": "*/*"}

    # 小分片：普通请求整块读，写缓存
    if not rng:
        try:
            resp = sess.get(url, headers=headers, timeout=60, allow_redirects=True)
            body = resp.content
            status = resp.status_code
            ctype = resp.headers.get("content-type", "application/octet-stream")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"upstream failed: {exc}") from exc
        finally:
            sess.close()
        if status >= 400:
            raise HTTPException(status, f"upstream {status}")
        if body:
            segcache.put(url, body)
        return Response(
            body,
            media_type=ctype,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
                "X-Seg-Cache": "miss" if body else "empty",
            },
        )

    # 带 Range（大文件拖动）：流式转发
    headers["Range"] = rng
    try:
        resp = sess.get(url, headers=headers, stream=True, timeout=120, allow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        sess.close()
        raise HTTPException(502, f"upstream failed: {exc}") from exc

    if resp.status_code >= 400:
        sess.close()
        raise HTTPException(resp.status_code, f"upstream {resp.status_code}")

    out: dict[str, str] = {"Access-Control-Allow-Origin": "*"}
    for k in ("content-type", "content-length", "content-range", "accept-ranges", "etag", "last-modified"):
        v = resp.headers.get(k)
        if v:
            out[k] = v
    out.setdefault("accept-ranges", "bytes")

    def stream():
        try:
            for chunk in resp.iter_content(65536):
                if chunk:
                    yield chunk
        finally:
            sess.close()

    return StreamingResponse(stream(), status_code=resp.status_code, headers=out)


@app.get("/api/cache-stats")
def api_cache_stats() -> dict[str, Any]:
    from . import segcache, thumb

    return {"segments": segcache.stats(), "thumbs": thumb.stats()}


@app.get("/api/img")
def api_img(u: str, r: str = "") -> Response:
    try:
        url = b64d(u)
        ref = b64d(r) if r else ""
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "bad base64") from exc
    if not host_allowed(url):
        raise HTTPException(403, "host not allowed")
    body, ctype = _fetch_bytes(url, referer=ref or _referer_for(url) or "/")
    return Response(
        body,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=86400", "Access-Control-Allow-Origin": "*"},
    )


@app.get("/api/thumb")
def api_thumb(u: str, t: float = 0.0, r: str = "", w: int = 320, k: str = "", iv: str = "") -> Response:
    """进度条预览帧：u=分片地址，t=片内秒数，r=Referer，k=AES 密钥地址，iv=AES IV。"""
    from .thumb import get_thumb

    try:
        body = get_thumb(u, t, r, max(120, min(640, w)), k, iv)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("thumb failed: %s", exc)
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc
    return Response(
        body,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800", "Access-Control-Allow-Origin": "*"},
    )


# ------------------------------------------------------------------------ frontend
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:  # pragma: no cover
    log.warning("web directory missing: %s", WEB_DIR)
