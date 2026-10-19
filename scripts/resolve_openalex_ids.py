#!/usr/bin/env python3
"""一次性脚本：用 OpenAlex API key 为每位学者解析作者 ID，写回 YAML。

验证规则：候选的姓与学者姓名一致（含重音字符归一化）才采纳。
用法: python3 scripts/resolve_openalex_ids.py
"""
import json
import sys
import time
import unicodedata
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "scholars.yaml"
BASE = "https://api.openalex.org"

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            import os
            os.environ.setdefault(k.strip(), v.strip())


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def search(name: str) -> list:
    params = {"search": name, "per_page": 5,
              "select": "id,display_name,last_known_institutions,works_count",
              "mailto": "dimo@trade-monitor.local"}
    key = __import__("os").environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    for attempt in range(5):
        try:
            r = requests.get(f"{BASE}/authors", params=params, timeout=40)
        except requests.RequestException:
            time.sleep(20)
            continue
        if r.status_code == 429:
            time.sleep(30)
            continue
        r.raise_for_status()
        return r.json().get("results", [])
    raise RuntimeError(f"限流: {name}")


def main():
    cfg = yaml.safe_load(CFG.read_text())
    n = 0
    for s in cfg["scholars"]:
        if not s.get("enabled", True) or not s.get("s2_id"):
            continue
        if s.get("openalex_id"):
            continue
        surname = norm(s["name"]).split()[-1]
        cands = search(s["name"])
        pick = None
        for a in cands:
            display = a.get("display_name", "")
            if norm(display).split()[-1:] == [surname] and a.get("works_count", 0) >= 30:
                pick = a
                break
        if pick:
            s["openalex_id"] = pick["id"].rsplit("/", 1)[-1]
            insts = ",".join(i["display_name"] for i in
                             (pick.get("last_known_institutions") or []))
            print(f"{s['name']}: {s['openalex_id']} ({display} | {insts} | "
                  f"{pick.get('works_count')}篇)")
            n += 1
        else:
            print(f"!! {s['name']}: 无姓氏匹配候选，保留待查")
        CFG.write_text(yaml.dump(cfg, allow_unicode=True, sort_keys=False))
        time.sleep(1.2)
    print(f"== 新解析 {n} 人 ==")


if __name__ == "__main__":
    sys.exit(main())
