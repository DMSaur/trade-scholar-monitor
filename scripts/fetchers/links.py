#!/usr/bin/env python3
"""推文外链解析：t.co 短链还原真实地址并抓网页标题，结果缓存。

X 的正文里所有链接都被替换成 t.co 短链，看不到目的地。这里在构建时
跟随跳转拿到真实 URL，再从页面里取 og:title / <title> 做预览卡片。
t.co 与多数外站在本机网络下需走代理，取 XREACH_PROXY 同款默认值。
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
PROXY = os.environ.get("XREACH_PROXY", "http://127.0.0.1:7897")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TCO = re.compile(r"https?://t\.co/\w+")
# 反爬虫墙的占位标题没有信息量，宁可只显示域名
JUNK_TITLE = re.compile(
    r"security verification|are you a robot|just a moment|access denied|"
    r"captcha|sign in to|log in to|attention required|bot verification|"
    r"enable javascript|cookies", re.I)


def _proxies():
    return {"http": PROXY, "https": PROXY} if PROXY else None


def _load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def cache_get(conn, url):
    row = conn.execute("SELECT * FROM link_cache WHERE url = ?", (url,)).fetchone()
    return dict(row) if row else None


def cache_put(conn, url, final_url="", title="", domain="", image=""):
    conn.execute(
        "INSERT OR REPLACE INTO link_cache (url, final_url, title, domain, image, resolved_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (url, final_url, title, domain, image,
         datetime.now().isoformat(timespec="seconds")))


def _extract_meta(html: str, final_url: str):
    def og(prop):
        m = re.search(
            rf'<meta[^>]+(?:property|name)=[\'"]{prop}[\'"][^>]+content=[\'"]([^\'"]+)',
            html, re.I) or re.search(
            rf'<meta[^>]+content=[\'"]([^\'"]+)[\'"][^>]+(?:property|name)=[\'"]{prop}[\'"]',
            html, re.I)
        return (m.group(1) if m else "").strip()

    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = (og("og:title") or og("twitter:title")
             or (m.group(1).strip() if m else ""))
    title = re.sub(r"\s+", " ", title)[:160]
    if JUNK_TITLE.search(title):
        title = ""  # 反爬虫墙的占位文本，弃用
    domain = (og("og:site_name")
              or urlparse(final_url).netloc.removeprefix("www."))
    image = og("og:image")[:400]
    return title, domain, image


def _fetch_page(url: str, max_bytes: int = 200_000):
    """GET 并返回 (最终URL, 响应文本前若干字节)。失败返回 (url, '')。"""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=12,
                         proxies=_proxies(), allow_redirects=True,
                         stream=True)
        final = str(r.url)
        content = b""
        for chunk in r.iter_content(65536):
            content += chunk
            if len(content) > max_bytes:
                break
        r.close()
        ctype = r.headers.get("Content-Type", "")
        text = content.decode("utf-8", "ignore") if "html" in ctype.lower() else ""
        return final, text
    except Exception:
        return url, ""


def _is_x_internal(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host in ("twitter.com", "www.twitter.com", "x.com", "www.x.com",
                    "t.co")


def resolve(url: str) -> dict | None:
    """t.co 短链 → {url, title, domain, image}。

    t.co 对脚本不做 301，而是返回一个把目的地放在 <title> 里的中转页。
    指向 X 自身（推文图片等）的链接与页面已有的缩略图重复，返回 None 跳过。
    """
    out = {"url": url, "title": "", "domain": "t.co", "image": ""}
    final, html = _fetch_page(url)
    title, domain, image = _extract_meta(html, final)
    dest = final
    if _is_x_internal(final) and title.startswith("http"):
        dest = title.strip()
        title, domain, image = "", "", ""
    if _is_x_internal(dest) and "t.co" not in urlparse(dest).netloc:
        return None  # X 内部链接（推文图片等），跳过
    out["url"] = dest
    if title.startswith("http"):
        title = ""
    if title:
        out["title"] = title
    if domain and not _is_x_internal(domain):
        out["domain"] = domain.removeprefix("www.")
    if image:
        out["image"] = image
    if out["url"] != url and not title:
        # 还差一步：抓真实页面取标题
        final2, html2 = _fetch_page(dest)
        if not _is_x_internal(final2):
            title, domain, image = _extract_meta(html2, final2)
            if title:
                out["title"] = re.sub(r"\s+", " ", title)[:160]
            if domain:
                out["domain"] = domain.removeprefix("www.")
            if image:
                out["image"] = image[:400]
    return out


def enrich(conn, limit: int = 30) -> int:
    """给库里推文条目的 extra 补 links 字段，返回本轮新解析的链接数。"""
    _load_env()
    rows = conn.execute(
        "SELECT uid, abstract, extra FROM items WHERE source='tweet'"
        " ORDER BY date DESC").fetchall()
    resolved = 0
    for r in rows:
        if resolved >= limit:
            break
        extra = json.loads(r["extra"] or "{}")
        urls = list(dict.fromkeys(TCO.findall(r["abstract"] or "")))[:4]
        if not urls:
            continue
        done = {l.get("tco") for l in extra.get("links", [])}
        if set(urls) <= done:
            continue
        links = list(extra.get("links", []))
        for u in urls:
            if u in done:
                continue
            hit = cache_get(conn, u)
            if hit is None:
                if resolved >= limit:
                    break  # 本轮配额用完，下轮继续
                info = resolve(u)
                resolved += 1
                if info is None:
                    # X 内部链接（推文图片等），与缩略图重复，标记跳过
                    cache_put(conn, u, "", "", "x-internal", "")
                    hit = cache_get(conn, u)
                else:
                    cache_put(conn, u, info["url"], info["title"],
                              info["domain"], info["image"])
                    hit = cache_get(conn, u)
            if hit and hit["domain"] == "x-internal":
                links.append({"tco": u, "skip": 1, "url": "", "title": "",
                              "domain": "", "image": ""})
            elif hit:
                links.append({"tco": u, "url": hit["final_url"],
                              "title": hit["title"], "domain": hit["domain"],
                              "image": hit["image"]})
        links = links[:4]
        extra["links"] = links
        conn.execute("UPDATE items SET extra = ? WHERE uid = ?",
                     (json.dumps(extra, ensure_ascii=False), r["uid"]))
    conn.commit()
    return resolved
