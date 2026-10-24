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
# 与 db.connect() 一致补列，让新字段走真实路径而不是防御取值
for col in ("title_zh", "abstract_zh"):
    try:
        conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT")
    except sqlite3.OperationalError:
        pass

# 一段超过分块阈值(1200字符)的英文摘要，验证长摘要折叠块
LONG_ABS = ("We study how tariffs propagate through global supply chains. " * 16
            + "Our quantitative model features multi-sector production networks. "
            * 14
            + "Counterfactual simulations show welfare losses concentrate in "
            "upstream industries, while downstream firms partially substitute "
            "toward domestic inputs and third-country suppliers adjust routes.")

MOCK = [
    dict(uid="oa:W1", source="top5", scholar_id=None,
         title="Tariffs and the Distribution of Welfare: Evidence from the 2018 Trade War",
         authors="David Autor, David Dorn, Gordon Hanson",
         venue="American Economic Review", url="https://doi.org/10.1257/aer.20240001",
         date="2026-10-15", abstract=LONG_ABS,
         extra={"journal_short": "AER", "keyword_hit": "tariff"},
         relevant=1, summary_zh="用2018年贸易战数据测算关税的福利分配效应，发现进口竞争地区受损最重。",
         title_zh="关税与福利分配：来自2018年贸易战的证据",
         abstract_zh="我们研究关税如何通过全球供应链传导。" * 20,
         tags='["关税", "贸易政策"]'),
    dict(uid="oa:W2", source="top5", scholar_id=None,
         title="Global Value Chains and the Rise of Services Trade",
         authors="Marc Melitz, Stephen Redding",
         venue="Quarterly Journal of Economics", url="https://doi.org/10.1093/qje/qjae002",
         date="2026-10-12", abstract="Services trade has grown faster than goods.",
         extra={"journal_short": "QJE", "keyword_hit": "value chain"},
         relevant=1, summary_zh="研究服务贸易增速超过货物贸易的原因，全球价值链重构是主要驱动力。",
         title_zh="全球价值链与服务贸易的兴起",
         abstract_zh="",  # 译文缺失时折叠块应只显示英文原文
         tags='["全球价值链"]'),
    dict(uid="nber:w34123", source="nber", scholar_id=None,
         title="Export Controls and Semiconductor Supply Chains: Evidence from Recent Restrictions",
         authors="Treb Allen, Costas Arkolakis",
         venue="NBER Working Paper", url="https://www.nber.org/papers/w34123",
         date="2026-10-16", abstract="We quantify the effect of export controls.",
         extra={"nber_id": "W34123", "keyword_hit": "export controls"},
         relevant=1, summary_zh="量化近期半导体出口管制对供应链的冲击，发现管制成本主要由出口国承担。",
         title_zh="出口管制与半导体供应链：来自近期限制的证据",
         abstract_zh="我们量化了出口管制的效应。",
         tags='["出口管制", "供应链"]'),
    dict(uid="s2:111", source="scholar", scholar_id="s2:2880987",
         title="Railroads and Trade Costs: New Estimates",
         authors="Dave Donaldson",
         venue="工作论文", url="https://www.semanticscholar.org/paper/111",
         date="2026-10-14", abstract="",  # 无摘要论文：不应渲染折叠块
         extra={"scholar_name": "Dave Donaldson"},
         relevant=1, summary_zh="更新铁路对贸易成本的估计，结果与既往研究一致但幅度更小。",
         title_zh="铁路与贸易成本：新估计",
         abstract_zh="",
         tags='["方法论"]'),
    dict(uid="tweet:1111", source="tweet", scholar_id="x:ChadBown",
         title="New paper day!", authors="@ChadBown", venue="X (Twitter)",
         url="https://x.com/ChadBown/status/1111",
         date="2026-10-17", abstract="HOW TO WIN A TRADE WAR is officially published in the US today!!!",
         extra={"handle": "ChadBown", "name": "Chad P. Bown", "is_retweet": False,
                "likes": 39, "retweets": 9, "views": 11735},
         relevant=1, summary_zh="Bown 宣布新书《如何打赢贸易战》美国正式出版。",
         title_zh="", abstract_zh="",
         tags='["贸易战"]'),
    dict(uid="tweet:2222", source="tweet", scholar_id="x:rodrikdani",
         title="RT on industrial policy", authors="@rodrikdani", venue="X (Twitter)",
         url="https://x.com/rodrikdani/status/2222",
         date="2026-10-16", abstract="RT @someone: Industrial policy is back, and this time it is global.",
         extra={"handle": "rodrikdani", "name": "Dani Rodrik", "is_retweet": True,
                "likes": 0, "retweets": 86, "views": 12000},
         relevant=1, summary_zh="Rodrik 转发观点：产业政策全面回归且已成全球现象。",
         title_zh="", abstract_zh="",
         tags='["产业政策"]'),
]

for m in MOCK:
    conn.execute(
        "INSERT INTO items (uid, source, scholar_id, title, authors, venue, url,"
        " date, abstract, extra, relevant, summary_zh, tags, first_seen,"
        " title_zh, abstract_zh)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (m["uid"], m["source"], m["scholar_id"], m["title"], m["authors"],
         m["venue"], m["url"], m["date"], m["abstract"],
         json.dumps(m["extra"], ensure_ascii=False), m["relevant"],
         m["summary_zh"], m["tags"], "2026-10-18T00:00:00",
         m.get("title_zh", ""), m.get("abstract_zh", "")))
conn.commit()

from build_site import build  # noqa: E402
scholars_list = [
    {"name": "Dave Donaldson", "s2_id": "2880987", "twitter": ""},
    {"name": "Chad Bown", "s2_id": "", "twitter": "ChadBown"},
    {"name": "Dani Rodrik", "s2_id": "", "twitter": "rodrikdani"},
]
# 写到临时目录，避免污染真实 docs/（build_site 通过 db.ROOT 定位输出目录）
import build_site as bs
from pathlib import Path as _P
import shutil as _sh
bs.db.ROOT = _P(tempfile.mkdtemp())
(bs.db.ROOT / "docs").mkdir(parents=True, exist_ok=True)
build(conn, scholars_list)
_sh.copy(bs.db.ROOT / "docs" / "index.html", "/tmp/mock_index.html")
print("mock 页面已生成 -> /tmp/mock_index.html")

# 最小断言：从内嵌 JSON 断结构，从渲染文本断内容
import re as _re
import json as _json

html = (bs.db.ROOT / "docs" / "index.html").read_text(encoding="utf-8")
payload = _json.loads(_re.search(
    r'<script id="page-data" type="application/json">(.*?)</script>',
    html, _re.S).group(1))
papers = [it for it in payload["items"] if it["source"] != "tweet"]
with_abs = [it for it in papers
            if (it["abstract"] or "").strip() or (it["abstract_zh"] or "").strip()]
checks = {
    # 带摘要的论文 3 篇（W1/W2/nber），无摘要论文与推文都不该进摘要展示
    "JSON 中带摘要论文数正确": len(with_abs) == 3,
    "英文原文已进页面数据": all("upstream industries" in it["abstract"]
                          for it in with_abs if len(it["abstract"]) > 1000),
    "中文译文已进页面数据": any("我们研究关税如何通过全球供应链传导" in it["abstract_zh"]
                          for it in with_abs),
    "渲染出折叠块正文": "我们研究关税如何通过全球供应链传导" in html
                  and "upstream industries" in html,
    "翻译缺失时只显示英文": "Services trade has grown faster than goods." in html,
}
failed = [k for k, ok in checks.items() if not ok]
if failed:
    print("!! 断言未通过:", failed)
    sys.exit(1)
print("mock 断言全部通过")
