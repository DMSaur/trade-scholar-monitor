#!/usr/bin/env python3
"""临时脚本：往测试库塞假数据并生成页面，验证前端渲染。"""
import sqlite3
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

# 指到临时库
tmp = Path(tempfile.mkdtemp()) / "test.db"
db.DB_PATH = tmp
conn = sqlite3.connect(tmp)
conn.row_factory = sqlite3.Row
conn.executescript(db.SCHEMA)

MOCK = [
    dict(uid="oa:W1", source="top5", scholar_id=None,
         title="Tariffs and the Distribution of Welfare: Evidence from the 2018 Trade War",
         authors="David Autor, David Dorn, Gordon Hanson",
         venue="American Economic Review", url="https://doi.org/10.1257/aer.20240001",
         date="2026-10-15", abstract="We study the welfare effects of tariffs.",
         extra={"journal_short": "AER", "keyword_hit": "tariff"},
         relevant=1, summary_zh="用2018年贸易战数据测算关税的福利分配效应，发现进口竞争地区受损最重。",
         tags='["关税", "贸易政策"]'),
    dict(uid="oa:W2", source="top5", scholar_id=None,
         title="Global Value Chains and the Rise of Services Trade",
         authors="Marc Melitz, Stephen Redding",
         venue="Quarterly Journal of Economics", url="https://doi.org/10.1093/qje/qjae002",
         date="2026-10-12", abstract="Services trade has grown faster than goods.",
         extra={"journal_short": "QJE", "keyword_hit": "value chain"},
         relevant=1, summary_zh="研究服务贸易增速超过货物贸易的原因，全球价值链重构是主要驱动力。",
         tags='["全球价值链"]'),
    dict(uid="nber:w34123", source="nber", scholar_id=None,
         title="Export Controls and Semiconductor Supply Chains: Evidence from Recent Restrictions",
         authors="Treb Allen, Costas Arkolakis",
         venue="NBER Working Paper", url="https://www.nber.org/papers/w34123",
         date="2026-10-16", abstract="We quantify the effect of export controls.",
         extra={"nber_id": "W34123", "keyword_hit": "export controls"},
         relevant=1, summary_zh="量化近期半导体出口管制对供应链的冲击，发现管制成本主要由出口国承担。",
         tags='["出口管制", "供应链"]'),
    dict(uid="s2:111", source="scholar", scholar_id="s2:2880987",
         title="Railroads and Trade Costs: New Estimates",
         authors="Dave Donaldson",
         venue="工作论文", url="https://www.semanticscholar.org/paper/111",
         date="2026-10-14", abstract="New estimates of railroad trade effects.",
         extra={"scholar_name": "Dave Donaldson"},
         relevant=1, summary_zh="更新铁路对贸易成本的估计，结果与既往研究一致但幅度更小。",
         tags='["方法论"]'),
    dict(uid="tweet:1111", source="tweet", scholar_id="x:ChadBown",
         title="New paper day!", authors="@ChadBown", venue="X (Twitter)",
         url="https://x.com/ChadBown/status/1111",
         date="2026-10-17", abstract="HOW TO WIN A TRADE WAR is officially published in the US today!!!",
         extra={"handle": "ChadBown", "name": "Chad P. Bown", "is_retweet": False,
                "likes": 39, "retweets": 9, "views": 11735},
         relevant=1, summary_zh="Bown 宣布新书《如何打赢贸易战》美国正式出版。",
         tags='["贸易战"]'),
    dict(uid="tweet:2222", source="tweet", scholar_id="x:rodrikdani",
         title="RT on industrial policy", authors="@rodrikdani", venue="X (Twitter)",
         url="https://x.com/rodrikdani/status/2222",
         date="2026-10-16", abstract="RT @someone: Industrial policy is back, and this time it is global.",
         extra={"handle": "rodrikdani", "name": "Dani Rodrik", "is_retweet": True,
                "likes": 0, "retweets": 86, "views": 12000},
         relevant=1, summary_zh="Rodrik 转发观点：产业政策全面回归且已成全球现象。",
         tags='["产业政策"]'),
]

for m in MOCK:
    conn.execute(
        "INSERT INTO items (uid, source, scholar_id, title, authors, venue, url,"
        " date, abstract, extra, relevant, summary_zh, tags, first_seen)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (m["uid"], m["source"], m["scholar_id"], m["title"], m["authors"],
         m["venue"], m["url"], m["date"], m["abstract"],
         json.dumps(m["extra"], ensure_ascii=False), m["relevant"],
         m["summary_zh"], m["tags"], "2026-10-18T00:00:00"))
conn.commit()

from build_site import build  # noqa: E402
scholars_list = [
    {"name": "Dave Donaldson", "s2_id": "2880987", "twitter": ""},
    {"name": "Chad Bown", "s2_id": "", "twitter": "ChadBown"},
    {"name": "Dani Rodrik", "s2_id": "", "twitter": "rodrikdani"},
]
build(conn, scholars_list)
print("mock 页面已生成 ->", ROOT / "docs" / "index.html")
