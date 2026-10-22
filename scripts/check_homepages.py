#!/usr/bin/env python3
"""核验学者主页候选:走本地代理拉页面,要求 200 且标题或正文含学者姓名。

只看状态码 200 会踩两个坑:Google Sites 的 site/XXX 不存在时也返回 200
(跳 Drive 登录页);个人域名有同名陷阱(evenett.com 是日本小说家的站,
Evenett 真站是 simon-evenett.com)。所以必须核对页面内容里的姓名。

输入 JSON 格式(列表):
  [{"key": "唯一标识", "en": "拼音或英文名", "url": "候选主页(可为空)"}]

用法:
  python3 scripts/check_homepages.py candidates.json result.json [--search]

  默认只核验给出的 url;--search 时对 url 为空的人用 curl_cffi 走代理请求
  DuckDuckGo lite 端点搜索(需 pip 安装 curl_cffi,普通 requests 会被
  202 风控挡死;遇到 202 退避 2 分钟,不要连续探测,封禁会刷新)。
  DuckDuckGo 按出口 IP 计数,每个干净 IP 只有 1-2 次信任窗,冷却约 1 小时,
  批量扫描要放慢节奏。

输出 result.json:{"key": "通过核验的 url"}。
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

PROXIES = {"https": "http://127.0.0.1:7897", "http": "http://127.0.0.1:7897"}
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
SKIP_DOMAINS = ("semanticscholar.org", "openalex.org", "nber.org/papers",
                "ideas.repec", "scholar.google", "econpapers")


def toks_of(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [t for t in re.sub(r"[^a-z\- ]", " ", s).split() if t]


def fetch(url):
    try:
        r = requests.get(url, proxies=PROXIES, timeout=30, headers=UA, verify=False)
        return r.status_code, r.text
    except Exception as e:
        return f"ERR:{type(e).__name__}", ""


def page_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r'property="og:title" content="([^"]+)"', html)
    return m.group(1).strip() if m else ""


def name_in(text, etoks):
    if not etoks:
        return False
    low = text.lower()
    if etoks[-1] not in low:
        return False
    return any(g[:3] in low for g in etoks[:-1]) if etoks[:-1] else True


def ddg_search(query):
    """DuckDuckGo lite 搜索,需 curl_cffi;202 时退避,不要连续探测。"""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        print("    未安装 curl_cffi,跳过搜索")
        return []
    from urllib.parse import quote, unquote
    for _ in range(3):
        r = creq.get(f"https://lite.duckduckgo.com/lite/?q={quote(query)}",
                     proxies=PROXIES, impersonate="chrome", timeout=30)
        if r.status_code == 200:
            return [unquote(u) for u in re.findall(r'uddg=([^&"]+)', r.text)]
        print(f"    DDG {r.status_code},退避 120 秒(封禁会刷新,勿连续探测)")
        time.sleep(120)
    return []


def main(cand_path, result_path, do_search):
    people = json.loads(Path(cand_path).read_text())
    result = {}
    p = Path(result_path)
    if p.exists():
        result = json.loads(p.read_text())

    for i, e in enumerate(people, 1):
        etoks = toks_of(e.get("en") or e.get("key"))
        url = e.get("url") or ""
        if not url and do_search:
            urls = ddg_search(f'"{e.get("en")}" economist homepage')
            for u in urls:
                if any(d in u for d in SKIP_DOMAINS):
                    continue
                code, html = fetch(u)
                if code == 200 and name_in(page_title(html), etoks):
                    url = u
                    break
                time.sleep(1)
        if url:
            code, html = fetch(url)
            ok = code == 200 and name_in(page_title(html) or html[:8000], etoks)
            if ok:
                result[e["key"]] = url
            print(f"[{i}/{len(people)}] {e.get('key', ''):20s} {code} "
                  f"{'留 ' if ok else '弃 '}{url[:70]}")
        else:
            print(f"[{i}/{len(people)}] {e.get('key', ''):20s} 无候选")
        p.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        time.sleep(1.5)
    print(f"== 通过 {len(result)} 条 ==", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], "--search" in sys.argv)
