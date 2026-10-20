#!/usr/bin/env python3
"""Top-5 经济学期刊最新论文：OpenAlex 按期刊 ISSN 拉取，贸易关键词初筛。"""
import time
from datetime import datetime

from .openalex_common import get_pages, inverted_abstract

# 国际经济学权威表述见 config/topics.yaml，这里只放期刊标识
JOURNALS = [
    {"name": "American Economic Review", "short": "AER", "issn": "0002-8282"},
    {"name": "Quarterly Journal of Economics", "short": "QJE", "issn": "0033-5533"},
    {"name": "Journal of Political Economy", "short": "JPE", "issn": "0022-3808"},
    {"name": "Econometrica", "short": "ECMA", "issn": "0012-9682"},
    {"name": "Review of Economic Studies", "short": "REStud", "issn": "0034-6527"},
]

SELECT = ("id,doi,title,authorships,publication_date,primary_location,"
          "abstract_inverted_index,type")


def _match(text: str, keywords: list) -> str | None:
    low = text.lower()
    for kw in keywords:
        if kw.lower() in low:
            return kw
    return None


def fetch(start_date: str, keywords: list) -> list[dict]:
    """返回近窗口内命中贸易关键词的候选条目（LLM 之后确认相关性）。"""
    items = []
    for j in JOURNALS:
        results = get_pages(
            "/works",
            {
                "filter": (f"primary_location.source.issn:{j['issn']},"
                           f"from_publication_date:{start_date}"),
                "select": SELECT,
                "sort": "publication_date:desc",
            },
            max_pages=4,
        )
        for w in results:
            if w.get("type") == "paratext":
                continue
            abstract = inverted_abstract(w.get("abstract_inverted_index"))
            title = w.get("title") or ""
            hit = _match(title, keywords) or _match(abstract, keywords)
            if not hit:
                continue
            auths = [a["author"]["display_name"]
                     for a in w.get("authorships", [])][:6]
            src = ((w.get("primary_location") or {}).get("source") or {})
            items.append({
                "uid": f"oa:{w['id'].rsplit('/', 1)[-1]}",
                "source": "top5",
                "title": title,
                "authors": ", ".join(auths),
                "venue": src.get("display_name") or j["short"],
                "url": w.get("doi") or w["id"],
                "date": w.get("publication_date"),
                "abstract": abstract[:4000],
                "extra": {"journal_short": j["short"], "keyword_hit": hit,
                          "doi": (w.get("doi") or "").replace("https://doi.org/", "")},
                "relevant": True,
            })
        time.sleep(1.0)
    return items
