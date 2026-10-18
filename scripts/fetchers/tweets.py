#!/usr/bin/env python3
"""学者推文：xreach CLI 抓取各学者 X 时间线（走本地代理）。

依赖: xreach (npm 全局)，本机路径 ~/.nvm/versions/node/*/bin/xreach。
XREACH_PROXY 为空字符串时可禁用代理。
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

XREACH_PROXY = os.environ.get("XREACH_PROXY", "http://127.0.0.1:7897")


def available() -> bool:
    return shutil.which("xreach") is not None


def _parse_time(s: str) -> datetime | None:
    # xreach 时间格式: Tue May 26 12:55:03 +0000 2026
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fetch_handle(handle: str, days: int, count: int = 40) -> list[dict]:
    """抓单个学者的时间线，返回窗口内的推文。"""
    cmd = ["xreach", "tweets", handle, "-n", str(count), "--format", "json",
           "--timeout", "30000"]
    if XREACH_PROXY:
        cmd += ["--proxy", XREACH_PROXY]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    ! xreach 运行失败 @{handle}: {e}")
        return []
    if r.returncode != 0:
        print(f"    ! xreach @{handle} 退出码 {r.returncode}: {r.stderr[:200]}")
        return []
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"    ! xreach @{handle} 输出解析失败")
        return []
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    out = []
    for t in items:
        dt = _parse_time(t.get("createdAt", ""))
        if not dt or dt < cutoff:
            continue
        author = (t.get("user") or {}).get("screenName", handle)
        tid = str(t.get("id", ""))
        is_rt = bool(t.get("isRetweet"))
        out.append({
            "uid": f"tweet:{tid}" if tid else f"tweet:{handle}:{dt.isoformat()}",
            "source": "tweet",
            "scholar_id": f"x:{handle}",
            "title": (t.get("text") or "").replace("\n", " ")[:140],
            "authors": f"@{author}",
            "venue": "X (Twitter)",
            "url": f"https://x.com/{author}/status/{tid}" if tid else "",
            "date": dt.strftime("%Y-%m-%d"),
            "abstract": t.get("text") or "",
            "extra": {
                "handle": handle,
                "name": (t.get("user") or {}).get("name", ""),
                "is_retweet": is_rt,
                "is_reply": bool(t.get("isReply")),
                "likes": t.get("likeCount", 0),
                "retweets": t.get("retweetCount", 0),
                "views": t.get("viewCount", 0),
                "created_at": dt.isoformat(),
            },
            "relevant": True,
        })
    return out


def fetch(scholars: list[dict], days: int) -> list[dict]:
    """对配置了 twitter 的启用学者逐个抓取。"""
    if not available():
        print("    ! xreach 不可用，本轮跳过推文板块")
        return []
    items = []
    for s in scholars:
        handle = (s.get("twitter") or "").lstrip("@")
        if not handle:
            continue
        got = fetch_handle(handle, days)
        print(f"    @{handle}: {len(got)} 条")
        items.extend(got)
    return items
