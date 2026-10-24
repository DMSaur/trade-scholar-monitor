#!/usr/bin/env python3
"""NBER 工作论文：OpenAlex 按 NBER 源过滤（S2809516038）。

注：NBER 官网 RSS 已在改版后失效，改用 OpenAlex 的 NBER 源，
数据同步且带完整摘要。
"""
import re
import time

from .openalex_common import get_pages, inverted_abstract

NBER_SOURCE = "S2809516038"
SELECT = ("id,doi,title,authorships,publication_date,primary_location,"
          "abstract_inverted_index,type,ids")
NBER_ID = re.compile(r"nber\.org/papers/(w\d+[a-z]?)", re.I)


def _match(text: str, keywords: list) -> str | None:
    """词边界匹配且容忍复数：safeguarding/important 不命中，tariffs 命中 tariff。"""
    low = (text or "").lower()
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw.lower())}s?\b", low):
            return kw
    return None


def fetch(start_date: str, keywords: list) -> list[dict]:
    items = []
    results = get_pages(
        "/works",
        {
            "filter": (f"primary_location.source.id:{NBER_SOURCE},"
                       f"from_publication_date:{start_date}"),
            "select": SELECT,
            "sort": "publication_date:desc",
        },
    )
    for w in results:
        abstract = inverted_abstract(w.get("abstract_inverted_index"))
        title = w.get("title") or ""
        hit = _match(title, keywords) or _match(abstract, keywords)
        if not hit:
            continue
        auths = [a["author"]["display_name"]
                 for a in w.get("authorships", [])][:6]
        landing = ((w.get("primary_location") or {})
                   .get("landing_page_url") or "")
        doi = w.get("doi") or ""
        # NBER 的 DOI 固定为 10.3386/w编号，比落地页更可靠
        m = (re.search(r"10\.3386/(w\d+[a-z]?)", doi, re.I)
             or NBER_ID.search(landing))
        wid = m.group(1).lower() if m else ""
        url = (f"https://www.nber.org/papers/{wid}" if wid
               else (doi or w["id"]))
        nber_label = wid.upper() if wid else ""
        if not wid:
            # 没有 NBER 编号时用 OpenAlex 内部编号做去重键
            wid = w["id"].rsplit("/", 1)[-1]
        items.append({
            "uid": f"nber:{wid}",
            "source": "nber",
            "title": title,
            "authors": ", ".join(auths),
            "venue": "NBER Working Paper",
            "url": url,
            "date": w.get("publication_date"),
            "abstract": abstract[:4000],
            "extra": {"nber_id": nber_label, "keyword_hit": hit},
            "relevant": True,
        })
    return items
