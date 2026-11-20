"""Dean Edwards packer unpacker — the player source is hidden inside eval(...)."""
from __future__ import annotations

import re

MARK = "eval(function(p,a,c,k,e,d){"
D36 = "0123456789abcdefghijklmnopqrstuvwxyz"
ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}


def _digit(n: int, base: int) -> str:
    if base <= 36 or n < 36:
        return D36[n]
    return chr(n + 29)


def _to_base(n: int, base: int) -> str:
    if n < base:
        return _digit(n, base)
    return _to_base(n // base, base) + _digit(n % base, base)


def _split_args(src: str, pos: int) -> list[str]:
    depth, i, args, cur, quote = 0, pos, [], [], None
    while i < len(src):
        ch = src[i]
        if quote:
            cur.append(ch)
            if ch == "\\":
                cur.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            cur.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
            if depth > 1:
                cur.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append("".join(cur).strip())
                return args
            cur.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    raise ValueError("unbalanced arguments")


def _unquote(lit: str) -> str:
    body, out, i = lit[1:-1], [], 0
    while i < len(body):
        if body[i] == "\\":
            nxt = body[i + 1] if i + 1 < len(body) else ""
            out.append(ESC.get(nxt, nxt))
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def unpack(html: str) -> list[str]:
    out: list[str] = []
    cursor = 0
    while True:
        start = html.find(MARK, cursor)
        if start < 0:
            break
        brace = html.find("{", start)
        depth, k = 0, brace
        while k < len(html):
            if html[k] == "{":
                depth += 1
            elif html[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        body = html[brace : k + 1]
        cursor = k + 1
        try:
            args = _split_args(html, k + 1)
        except ValueError:
            continue
        if len(args) < 4:
            continue
        try:
            payload = _unquote(args[0])
            base = int(re.sub(r"\D", "", args[1]) or 0)
            count = int(re.sub(r"\D", "", args[2]) or 0)
        except (ValueError, IndexError):
            continue
        word = re.search(r"'((?:[^'\\]|\\.)*)'", args[3])
        if not word or base <= 0 or count <= 0:
            continue
        words = _unquote(word.group(0)).split("|")
        if len(words) < 2:
            continue
        compound = "parseInt" in body
        text = payload
        for idx in range(count - 1, -1, -1):
            if idx >= len(words) or not words[idx]:
                continue
            token = _to_base(idx, base) if compound else _digit(idx, 36)
            text = re.sub(r"\b" + re.escape(token) + r"\b", words[idx].replace("\\", "\\\\"), text)
        out.append(text)
    return out


SRC_RE = re.compile(r"(?:^|[;\s])([A-Za-z_$][\w$]*)\s*=\s*'([^']+\.m3u8[^']*)'")
RES_RE = re.compile(r"(\d{3,4})x(\d{3,4})")


def m3u8_urls(html: str) -> list[dict]:
    found: dict[str, dict] = {}
    for block in unpack(html):
        for _var, url in SRC_RE.findall(block):
            if not url.startswith("http"):
                continue
            res = RES_RE.search(url)
            height = int(res.group(2)) if res else 0
            found[url] = {
                "url": url,
                "kind": "variant" if res else "master",
                "quality": res.group(0) if res else "master",
                "height": height,
            }
    return sorted(found.values(), key=lambda s: -s["height"])
