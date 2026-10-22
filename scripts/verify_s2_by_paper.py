#!/usr/bin/env python3
"""用代表作反查核验/修正 S2 作者 ID。

背景:S2 的 affiliations 字段多为空,同名学者靠 hIndex 最高者裸选会配错
(真实案例:Jeffrey Frankel 被建议配到一位心内科医生)。可靠做法是拿学者
一篇代表作的 DOI 到 S2 单篇查询,谁的名下署名这篇论文就是谁;当前 s2_id
未署名该论文时,在署名作者里按姓名匹配,唯一命中直接采用,多个命中再用
批量接口比 hIndex 取主档案。

输入 JSON 格式(列表):
  [{"key": "唯一标识", "en": "拼音或英文名", "openalex_id": "A...", "s2_id": "..."}]

用法:
  python3 scripts/verify_s2_by_paper.py candidates.json report.json

可断点续跑:report.json 里 status=ok 的条目自动跳过。走本地代理 127.0.0.1:7897。
"""
import json
import re
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()

ROOT = Path(__file__).resolve().parent.parent
OA_KEY = ""
for line in (ROOT / ".env").open():
    line = line.strip()
    if line.startswith("OPENALEX_API_KEY="):
        OA_KEY = line.split("=", 1)[1].strip()

OAS = requests.Session()
OAS.params = {"api_key": OA_KEY}
S2 = requests.Session()
S2.proxies = {"https": "http://127.0.0.1:7897", "http": "http://127.0.0.1:7897"}


def norm(t):
    s = unicodedata.normalize("NFKD", (t or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z\- ]", " ", s)


def norm_title(t):
    return norm(t).split()


def oa_representative(aid):
    """代表作:2018 年以来被引最高且有 DOI 的一篇(标题至少 6 个词)。"""
    r = OAS.get("https://api.openalex.org/works",
                params={"filter": f"author.id:{aid},from_publication_date:2018-01-01",
                        "per_page": 25, "sort": "cited_by_count:desc",
                        "select": "title,doi"}, timeout=40).json()
    for w in r.get("results", []):
        t = w.get("title") or ""
        if len(t.split()) >= 6 and w.get("doi"):
            return t, w["doi"].replace("https://doi.org/", "")
    for w in r.get("results", []):
        t = w.get("title") or ""
        if len(t.split()) >= 6:
            return t, ""
    return "", ""


def s2_paper_by_doi(doi):
    r = S2.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi)}",
               params={"fields": "title,authors.name,authors.authorId"}, timeout=30)
    if r.status_code == 404:
        return []
    if r.status_code in (429, 504):
        time.sleep(15)
        return s2_paper_by_doi(doi)
    r.raise_for_status()
    return [r.json()]


def s2_by_title(title):
    r = S2.get("https://api.semanticscholar.org/graph/v1/paper/search",
               params={"query": title, "fields": "title,authors.name,authors.authorId",
                       "limit": 5}, timeout=30)
    if r.status_code in (429, 504):
        time.sleep(15)
        return s2_by_title(title)
    if r.status_code >= 400:
        return []
    want = norm_title(title)[:12]
    return [p for p in r.json().get("data", [])
            if norm_title(p.get("title"))[:12] == want]


def batch_hindex(ids):
    out = {}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        for _ in range(8):
            r = S2.post("https://api.semanticscholar.org/graph/v1/author/batch",
                        params={"fields": "hIndex"}, json={"ids": chunk}, timeout=60)
            if r.status_code in (429, 504):
                time.sleep(20)
                continue
            if r.status_code == 400:
                break
            r.raise_for_status()
            for aid, d in zip(chunk, r.json()):
                out[aid] = (d or {}).get("hIndex") or 0
            break
    return out


def main(cand_path, report_path):
    people = json.loads(Path(cand_path).read_text())
    report = {}
    p = Path(report_path)
    if p.exists():
        report = json.loads(p.read_text())

    # 阶段 A:每人代表作反查署名
    pending = [e for e in people
               if not (report.get(e["key"], {}).get("status") == "ok")]
    for i, e in enumerate(pending, 1):
        if not e.get("openalex_id"):
            report[e["key"]] = {"status": "no-oa"}
            continue
        title, doi = oa_representative(e["openalex_id"])
        if not title:
            report[e["key"]] = {"status": "no-title"}
            continue
        papers = s2_paper_by_doi(doi) if doi else []
        if not papers:
            papers = s2_by_title(title)
        if not papers:
            report[e["key"]] = {"status": "title-not-found", "title": title}
            print(f"[A {i}/{len(pending)}] {e['key']}: 找不到论文", flush=True)
            continue
        authors = [(a["authorId"], a["name"]) for a in papers[0].get("authors", [])
                   if a.get("authorId")]
        cur = e.get("s2_id")
        if cur and cur in {aid for aid, _ in authors}:
            report[e["key"]] = {"status": "ok", "title": title, "current_ok": True}
            print(f"[A {i}/{len(pending)}] {e['key']}: 确认", flush=True)
            continue
        sur = norm(e["en"]).split()[-1]
        given = set(norm(e["en"]).split()[:-1])
        matched = []
        for aid, nm in authors:
            toks = norm(nm).split()
            if not toks or toks[-1] != sur:
                continue
            if given & set(toks[:-1]) or any(
                    t and any(g.startswith(t[0]) for g in given) for t in toks[:-1]):
                matched.append([aid, nm])
        report[e["key"]] = {"status": "phase-b", "title": title,
                            "matched": matched, "all_ids": [aid for aid, _ in authors]}
        print(f"[A {i}/{len(pending)}] {e['key']}: 待定 "
              f"{len(matched)} 命中/共 {len(authors)} 作者", flush=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=1))
        time.sleep(1.5)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1))

    # 阶段 B:所有待定者的候选档案,一次批量取 hIndex 后择主档
    all_ids = set()
    for e in people:
        rec = report.get(e["key"])
        if rec and rec.get("status") == "phase-b":
            pairs = rec["matched"] or [[x, ""] for x in rec["all_ids"]]
            for pair in pairs:
                all_ids.add(pair[0] if isinstance(pair, list) else pair)
    hmap = batch_hindex(sorted(all_ids))
    print(f"[B] 批量取回 {len(hmap)}/{len(all_ids)} 个 hIndex", flush=True)

    for e in people:
        rec = report.get(e["key"])
        if not rec or rec.get("status") != "phase-b":
            continue
        pairs = rec["matched"] or [[x, ""] for x in rec["all_ids"]]
        ranked = sorted(pairs,
                        key=lambda x: hmap.get(x[0] if isinstance(x, list) else x, 0),
                        reverse=True)
        if ranked:
            top = ranked[0]
            aid = top[0] if isinstance(top, list) else top
            nm = top[1] if isinstance(top, list) and len(top) > 1 else ""
            rec["status"] = "fixed"
            rec["suggestion"] = aid
            rec["suggestion_name"] = nm
        else:
            rec["status"] = "no-author"
        print(f"[B] {e['key']}: -> {rec.get('suggestion', '')}", flush=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("== 核验完成 ==", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
