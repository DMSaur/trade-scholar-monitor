#!/usr/bin/env python3
"""贸易学者最新论文：Semantic Scholar 按作者批量拉取。

选 S2 而非 OpenAlex 的原因：作者批量端点一次请求可带全部学者，
免费额度独立（不与 OpenAlex 的共享 IP 池争抢）。
"""
import time

import requests

BASE = "https://api.semanticscholar.org/graph/v1"
BATCH_FIELDS = ("papers.title,papers.abstract,papers.venue,papers.year,"
                "papers.publicationDate,papers.externalIds,papers.authors")


def _batch_once(chunk: list, max_retry: int = 6):
    """请求一组，返回 (成功, 结果列表或None, 错误信息)。结果与入参顺序对齐。"""
    for attempt in range(max_retry):
        try:
            r = requests.post(
                f"{BASE}/author/batch",
                params={"fields": BATCH_FIELDS},
                json={"ids": chunk},
                timeout=60,
            )
        except requests.RequestException:
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code in (429, 504):
            wait = 20 * (attempt + 1)
            print(f"    S2 429，等 {wait}s 重试")
            time.sleep(wait)
            continue
        if r.status_code == 400 and "exceed" in r.text.lower():
            return False, None, "exceed"
        if r.ok:
            return True, r.json(), ""
        return False, None, f"HTTP {r.status_code}: {r.text[:120]}"
    return False, None, "重试耗尽"


def _request_batch(ids: list) -> list:
    """按人分组请求，超返回体积上限时对半拆分。返回与入参顺序对齐。"""
    result: dict = {}
    queue = [ids]
    while queue:
        chunk = queue.pop(0)
        ok, data, err = _batch_once(chunk)
        if ok:
            result.update(dict(zip(chunk, data)))
            print(f"    S2 批量 {len(chunk)} 人成功")
        elif err == "exceed" and len(chunk) > 1:
            half = max(1, len(chunk) // 2)
            queue[0:0] = [chunk[:half], chunk[half:]]
            print(f"    S2 返回超限，{len(chunk)} 人拆成两组")
        else:
            raise RuntimeError(f"S2 批量接口失败: {err}")
        time.sleep(1.0)
    return [result.get(i) for i in ids]


def fetch(start_date: str, scholars: list[dict]) -> list[dict]:
    """按 s2_id 批量拉取每位学者窗口内的论文。"""
    valid = [s for s in scholars if s.get("s2_id")]
    if not valid:
        return []
    data = _request_batch([s["s2_id"] for s in valid])
    items = []
    for s, author in zip(valid, data):
        if not author:
            continue
        for p in author.get("papers") or []:
            pub_date = p.get("publicationDate")
            year = p.get("year")
            if pub_date:
                if pub_date < start_date:
                    continue
            elif year and f"{year}" >= start_date[:4]:
                pub_date = f"{year}-01-01"
            else:
                continue
            ext = p.get("externalIds") or {}
            doi = ext.get("DOI")
            corpus = ext.get("CorpusId")
            url = (f"https://doi.org/{doi}" if doi else
                   (f"https://www.semanticscholar.org/paper/{corpus}"
                    if corpus else ""))
            auths = [a.get("name", "") for a in p.get("authors", [])][:6]
            items.append({
                "uid": f"s2:{corpus or doi or abs(hash(p.get('title')))%10**10}",
                "source": "scholar",
                "scholar_id": f"s2:{s['s2_id']}",
                "title": p.get("title") or "",
                "authors": ", ".join(auths),
                "venue": p.get("venue") or "工作论文",
                "url": url,
                "date": pub_date,
                "abstract": (p.get("abstract") or "")[:4000],
                "extra": {"scholar_name": s["name"]},
                "relevant": True,
            })
        time.sleep(0.5)
    return items
