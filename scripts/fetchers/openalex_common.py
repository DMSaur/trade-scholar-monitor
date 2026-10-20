#!/usr/bin/env python3
"""OpenAlex API 公共封装：限流退避、直连与代理双路切换、摘要倒排还原。

OpenAlex 免费额度按 IP 共享，直连 429 时自动改走本地代理换出口 IP。
"""
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
BASE = "https://api.openalex.org"
MAILTO = "dimo@trade-monitor.local"
PROXY = os.environ.get("OPENALEX_PROXY", "http://127.0.0.1:7897")
SESSION = requests.Session()


def _load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


def get(path: str, params: dict, max_retry: int = 10) -> dict:
    params = dict(params)
    params.setdefault("mailto", MAILTO)
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    use_proxy = False  # 先直连，429 后切代理，两条路轮流
    for attempt in range(max_retry):
        proxies = {"http": PROXY, "https": PROXY} if use_proxy else None
        try:
            r = SESSION.get(f"{BASE}{path}", params=params, timeout=40,
                            proxies=proxies)
        except requests.RequestException:
            use_proxy = not use_proxy
            time.sleep(2)
            continue
        if r.status_code == 429:
            wait = min(6 * (attempt + 1), 60)
            print(f"    OpenAlex 429（{'代理' if use_proxy else '直连'}），"
                  f"{wait}s 后切换重试")
            use_proxy = not use_proxy
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"OpenAlex 重试耗尽: {path}")


def get_pages(path: str, params: dict, max_pages: int = 8,
              per_page: int = 100) -> list:
    """分页拉取直到某页不满（窗口内条目取完）或达到页数上限。

    params 里应已含 from_publication_date 过滤，服务端只返回窗口内条目。
    """
    results = []
    for page in range(1, max_pages + 1):
        p = dict(params)
        p["per_page"] = per_page
        p["page"] = page
        batch = get(path, p).get("results", [])
        results.extend(batch)
        if len(batch) < per_page:
            break
        time.sleep(0.5)
    return results


def inverted_abstract(inv: dict) -> str:
    """把 OpenAlex 的 abstract_inverted_index 还原为纯文本。"""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))
