#!/usr/bin/env python3
"""把 /tmp/s2_lookup.json 查到的 s2_id 回填进 config/scholars.yaml。

用法: python3 scripts/fill_scholars.py
核对规则：锚点 expected 名单里的学者才回填（避免同名误配）。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOOKUP = Path("/tmp/s2_lookup.json")
CFG = ROOT / "config" / "scholars.yaml"


def main():
    data = json.loads(LOOKUP.read_text())
    resolved = {}
    for entry in data.values():
        for name, aid in entry["got"].items():
            if name in entry["expected"]:
                resolved[name] = aid
    print(f"锚点数据可确认 {len(resolved)} 人:", sorted(resolved))

    text = CFG.read_text()
    n = 0
    for name, aid in resolved.items():
        # 只填该学者行中为空的 s2_id
        pattern = re.compile(
            r'(\{name: %s,[^\n]*?s2_id: )""' % re.escape(name))
        new_text, k = pattern.subn(rf'\g<1>"{aid}"', text)
        if k:
            text = new_text
            n += k
    CFG.write_text(text)
    print(f"已回填 {n} 人到 {CFG}")
    missing = [ln.strip() for ln in text.splitlines()
               if re.search(r"enabled(?::|:)", ln) is None
               and "s2_id: \"\"" in ln and not ln.strip().startswith("#")]
    if missing:
        print("仍缺 s2_id 的行数:", len(missing))


if __name__ == "__main__":
    sys.exit(main())
