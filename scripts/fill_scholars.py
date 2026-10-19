#!/usr/bin/env python3
"""把 /tmp/s2_lookup.json 查到的 s2_id 回填进 config/scholars.yaml。

匹配规则：锚点论文的作者列表里，规范名全等，或「姓相同 + 名首字母相同」
（S2 常返回 D. Dorn 一类缩写）。只在锚点的作者列表内匹配，避免同名误配。

用法: python3 scripts/fill_scholars.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOOKUP = Path("/tmp/s2_lookup.json")
CFG = ROOT / "config" / "scholars.yaml"

ALIAS = {
    "pol antras": "pol antras", "pol antràs": "pol antras",
    "pinelopi koujianou goldberg": "pinelopi goldberg",
    "pinelopi k. goldberg": "pinelopi goldberg",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace(".", "").strip())


def surname(n: str) -> str:
    return norm(n).split()[-1]


def initial(n: str) -> str:
    return norm(n).split()[0][0]


def match(expected: str, got_names: list) -> str | None:
    ne = ALIAS.get(norm(expected), norm(expected))
    surname_e = surname(ne)
    initial_e = initial(ne)
    first_e = ne.split()[0]
    exact, hits = [], []
    for g in got_names:
        ng = ALIAS.get(norm(g), norm(g))
        if ng == ne:
            return g
        if surname(ng) == surname_e and initial(ng) == initial_e:
            hits.append(g)
            if ng.split()[0] == first_e:
                exact.append(g)
    if len(hits) == 1:
        return hits[0]
    # 多个同姓候选：名与规范名首个词一致者优先（Robert C. Feenstra 优于 R. Feenstra）
    if exact:
        return exact[0]
    return None


def main():
    data = json.loads(LOOKUP.read_text())
    resolved = {}
    for entry in data.values():
        got_names = list(entry["got"].keys())
        for name in entry["expected"]:
            g = match(name, got_names)
            if g and name not in resolved:
                resolved[name] = entry["got"][g]
    print(f"锚点数据可确认 {len(resolved)} 人:", sorted(resolved))

    text = CFG.read_text()
    n = 0
    for name, aid in resolved.items():
        pattern = re.compile(
            r'(\{name: %s,[^\n]*?s2_id: )""' % re.escape(name))
        new_text, k = pattern.subn(rf'\g<1>"{aid}"', text)
        if k:
            text = new_text
            n += k
    CFG.write_text(text)
    print(f"已回填 {n} 人到 {CFG}")
    left = [ln.split("name: ")[1].split(",")[0] for ln in text.splitlines()
            if 's2_id: ""' in ln and "enabled" not in ln]
    if left:
        print("仍缺 s2_id:", "、".join(left))


if __name__ == "__main__":
    main()
