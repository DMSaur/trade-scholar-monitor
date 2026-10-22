#!/usr/bin/env python3
"""贸易学者最新论文：OpenAlex 按作者查询（日期可靠），失败时降级 S2 批量。"""
import time

from .openalex_common import get_pages, inverted_abstract

OA_SELECT = ("id,doi,title,authorships,publication_date,primary_location,"
             "abstract_inverted_index,type")


def _fetch_openalex(start_date: str, scholars: list[dict]) -> list[dict]:
    items = []
    for s in scholars:
        results = get_pages(
            "/works",
            {
                "filter": (f"author.id:{s['openalex_id']},"
                           f"from_publication_date:{start_date}"),
                "select": OA_SELECT,
                "sort": "publication_date:desc",
            },
            max_pages=4,
            per_page=100,
        )
        for w in results:
            if w.get("type") == "paratext":
                continue
            abstract = inverted_abstract(w.get("abstract_inverted_index"))
            auths = [a["author"]["display_name"]
                     for a in w.get("authorships", [])][:6]
            src = ((w.get("primary_location") or {}).get("source") or {})
            venue = src.get("display_name")
            wtype = w.get("type") or ""
            if not venue:
                venue = {"preprint": "预印本", "report": "报告"}.get(wtype, wtype)
            items.append({
                "uid": f"oa:{w['id'].rsplit('/', 1)[-1]}",
                "source": "scholar",
                "scholar_id": f"oa:{s['openalex_id']}",
                "title": w.get("title") or "",
                "authors": ", ".join(auths),
                "venue": venue,
                "url": w.get("doi") or w["id"],
                "date": w.get("publication_date"),
                "abstract": abstract[:4000],
                "extra": {"scholar_name": s["name"], "work_type": wtype,
                          "doi": (w.get("doi") or "").replace("https://doi.org/", "")},
                "relevant": True,
            })
        time.sleep(1.0)
    return items


def _fetch_s2(start_date: str, scholars: list[dict]) -> list[dict]:
    """S2 备用源：作者批量接口，响应超限时自动拆分与去摘要降级。"""
    import requests
    BASE_S2 = "https://api.semanticscholar.org/graph/v1"
    FIELDS_FULL = ("papers.title,papers.abstract,papers.venue,papers.year,"
                   "papers.publicationDate,papers.externalIds,papers.authors")
    FIELDS_LIGHT = FIELDS_FULL.replace(",papers.abstract", "")

    def batch_once(chunk, fields, max_retry=6):
        for attempt in range(max_retry):
            try:
                r = requests.post(f"{BASE_S2}/author/batch",
                                  params={"fields": fields},
                                  json={"ids": chunk}, timeout=60)
            except requests.RequestException:
                time.sleep(15 * (attempt + 1))
                continue
            if r.status_code in (429, 504):
                time.sleep(20 * (attempt + 1))
                continue
            if r.status_code == 400 and "exceed" in r.text.lower():
                return False, None, "exceed"
            if r.ok:
                return True, r.json(), ""
            return False, None, f"HTTP {r.status_code}"
        return False, None, "重试耗尽"

    valid = [s for s in scholars if s.get("s2_id")]
    if not valid:
        return []
    result, queue = {}, [( [s["s2_id"] for s in valid], FIELDS_FULL)]
    id2s = {s["s2_id"]: s for s in valid}
    while queue:
        chunk, fields = queue.pop(0)
        ok, data, err = batch_once(chunk, fields)
        if ok:
            result.update(dict(zip(chunk, data)))
        elif err == "exceed" and len(chunk) > 1:
            half = max(1, len(chunk) // 2)
            queue[0:0] = [(chunk[:half], fields), (chunk[half:], fields)]
        elif err == "exceed" and fields != FIELDS_LIGHT:
            queue[0:0] = [(chunk, FIELDS_LIGHT)]
        else:
            raise RuntimeError(f"S2 批量失败: {err}")
        time.sleep(1.0)

    items = []
    for aid, author in result.items():
        if not author:
            continue
        s = id2s[aid]
        for p in author.get("papers") or []:
            pub_date = p.get("publicationDate")
            year = p.get("year")
            if pub_date:
                if pub_date < start_date:
                    continue
            elif year and str(year) >= start_date[:4]:
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
                "scholar_id": f"s2:{aid}",
                "title": p.get("title") or "",
                "authors": ", ".join(auths),
                "venue": p.get("venue") or "工作论文",
                "url": url,
                "date": pub_date,
                "abstract": (p.get("abstract") or "")[:4000],
                "extra": {"scholar_name": s["name"]},
                "relevant": True,
            })
    return items


def fetch(start_date: str, scholars: list[dict]) -> list[dict]:
    """OpenAlex 主源；整体失败时降级 Semantic Scholar。"""
    with_oa = [s for s in scholars if s.get("openalex_id")]
    if with_oa:
        try:
            return _fetch_openalex(start_date, with_oa)
        except Exception as e:
            print(f"    ! OpenAlex 学者查询失败（{e}），降级 S2 批量")
    return _fetch_s2(start_date, scholars)
