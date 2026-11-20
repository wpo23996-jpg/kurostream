"""Payment channels: configuration + per-order instructions.

This build ships with manual settlement (user pays, you confirm).
Plug a real gateway by adding a channel that implements:
    create(order) -> dict  |  verify(callback_payload) -> bool
"""
from __future__ import annotations

import os
from typing import Any

CHANNEL_DEFS: dict[str, dict[str, str]] = {
    "alipay": {
        "key": "alipay",
        "label": "支付宝",
        "desc": "扫码或转账，备注订单号",
        "env": "KS_PAY_ALIPAY",
    },
    "usdt": {
        "key": "usdt",
        "label": "USDT · TRC20",
        "desc": "链上转账，备注订单号",
        "env": "KS_PAY_USDT",
    },
    "manual": {
        "key": "manual",
        "label": "人工客服",
        "desc": "联系客服获取收款方式",
        "env": "KS_PAY_MANUAL",
    },
}


def _account(channel: str) -> str:
    return os.getenv(CHANNEL_DEFS[channel]["env"], "").strip()


def channels() -> list[dict[str, Any]]:
    """Only channels with a configured account are offered."""
    out = []
    for key, meta in CHANNEL_DEFS.items():
        account = _account(key)
        if account or key == "manual":
            out.append(
                {
                    "key": key,
                    "label": meta["label"],
                    "desc": meta["desc"],
                    "configured": bool(account),
                }
            )
    return out


def default_channel() -> str:
    for c in channels():
        if c["configured"]:
            return c["key"]
    return "manual"


def instructions(channel: str, order: dict[str, Any]) -> dict[str, Any]:
    meta = CHANNEL_DEFS.get(channel, CHANNEL_DEFS["manual"])
    account = _account(channel)
    amount = order.get("amount", 0)
    no = order.get("order_no", "")
    note = os.getenv("KS_PAY_NOTE", "付款时务必备注订单号，否则无法自动到账确认")

    if channel == "alipay":
        body = f"支付宝转账 ¥{amount:.2f}，备注 {no}"
    elif channel == "usdt":
        body = f"转入 {amount:.2f} USDT（TRC20），备注 {no}"
    else:
        body = f"联系客服购买 {order.get('tier_name', '')}，金额 ¥{amount:.2f}"

    return {
        "channel": channel,
        "label": meta["label"],
        "account": account,
        "amount": amount,
        "order_no": no,
        "title": body,
        "note": note,
        "configured": bool(account),
    }
