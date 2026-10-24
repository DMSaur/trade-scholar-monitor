#!/usr/bin/env python3
"""临时脚本：往测试库塞假数据并生成页面，验证前端渲染。"""
import sqlite3
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

# mock 日期相对今天生成，保证任何日期跑都落在 30 日主题窗口内
def d_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")

D1, D2, D3, D4 = d_ago(2), d_ago(5), d_ago(3), d_ago(4)
T1, T2 = d_ago(1), d_ago(2)
FIRST_SEEN = datetime.now().isoformat(timespec="seconds")

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
         date=D1, abstract=LONG_ABS,
         extra={"journal_short": "AER", "keyword_hit": "tariff"},
         relevant=1, summary_zh="用2018年贸易战数据测算关税的福利分配效应，发现进口竞争地区受损最重。",
         title_zh="关税与福利分配：来自2018年贸易战的证据",
         abstract_zh="我们研究关税如何通过全球供应链传导。" * 20,
         tags='["关税", "贸易政策"]'),
    dict(uid="oa:W2", source="top5", scholar_id=None,
         title="Global Value Chains and the Rise of Services Trade",
         authors="Marc Melitz, Stephen Redding",
         venue="Quarterly Journal of Economics", url="https://doi.org/10.1093/qje/qjae002",
         date=D2, abstract="Services trade has grown faster than goods.",
         extra={"journal_short": "QJE", "keyword_hit": "value chain"},
         relevant=1, summary_zh="研究服务贸易增速超过货物贸易的原因，全球价值链重构是主要驱动力。",
         title_zh="全球价值链与服务贸易的兴起",
         abstract_zh="",  # 译文缺失时折叠块应只显示英文原文
         tags='["全球价值链"]'),
    dict(uid="nber:w34123", source="nber", scholar_id=None,
         title="Export Controls and Semiconductor Supply Chains: Evidence from Recent Restrictions",
         authors="Treb Allen, Costas Arkolakis",
         venue="NBER Working Paper", url="https://www.nber.org/papers/w34123",
         date=T2, abstract="We quantify the effect of export controls.",
         extra={"nber_id": "W34123", "keyword_hit": "export controls"},
         relevant=1, summary_zh="量化近期半导体出口管制对供应链的冲击，发现管制成本主要由出口国承担。",
         title_zh="出口管制与半导体供应链：来自近期限制的证据",
         abstract_zh="我们量化了出口管制的效应。",
         tags='["出口管制", "供应链"]'),
    dict(uid="s2:111", source="scholar", scholar_id="s2:2880987",
         title="Railroads and Trade Costs: New Estimates",
         authors="Dave Donaldson",
         venue="工作论文", url="https://www.semanticscholar.org/paper/111",
         date=D4, abstract="",  # 无摘要论文：不应渲染折叠块
         extra={"scholar_name": "Dave Donaldson"},
         relevant=1, summary_zh="更新铁路对贸易成本的估计，结果与既往研究一致但幅度更小。",
         title_zh="铁路与贸易成本：新估计",
         abstract_zh="",
         tags='["方法论"]'),
    dict(uid="tweet:1111", source="tweet", scholar_id="x:ChadBown",
         title="New paper day!", authors="@ChadBown", venue="X (Twitter)",
         url="https://x.com/ChadBown/status/1111",
         date=T1, abstract="HOW TO WIN A TRADE WAR is officially published in the US today!!!",
         extra={"handle": "ChadBown", "name": "Chad P. Bown", "is_retweet": False,
                "likes": 39, "retweets": 9, "views": 11735},
         relevant=1, summary_zh="Bown 宣布新书《如何打赢贸易战》美国正式出版。",
         title_zh="", abstract_zh="",
         tags='["贸易战"]'),
    dict(uid="tweet:2222", source="tweet", scholar_id="x:rodrikdani",
         title="RT on industrial policy", authors="@rodrikdani", venue="X (Twitter)",
         url="https://x.com/rodrikdani/status/2222",
         date=T2, abstract="RT @someone: Industrial policy is back, and this time it is global.",
         extra={"handle": "rodrikdani", "name": "Dani Rodrik", "is_retweet": True,
                "likes": 0, "retweets": 86, "views": 12000},
         relevant=1, summary_zh="Rodrik 转发观点：产业政策全面回归且已成全球现象。",
         title_zh="", abstract_zh="",
         tags='["产业政策"]'),
]

for m in MOCK:
    conn.execute(
        "INSERT INTO items (uid, source, scholar_id, title, authors, venue,"
        " url, date, abstract, extra, relevant, summary_zh, tags, first_seen,"
        " title_zh, abstract_zh)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (m["uid"], m["source"], m["scholar_id"], m["title"], m["authors"],
         m["venue"], m["url"], m["date"], m["abstract"],
         json.dumps(m["extra"], ensure_ascii=False), m["relevant"],
         m["summary_zh"], m["tags"], FIRST_SEEN,
         m.get("title_zh", ""), m.get("abstract_zh", "")))
conn.commit()

# ---- 会议板块 mock：一场未来（含置顶断言）、一场过去（含库内继承断言） ----
def d_ahead(n: int) -> str:
    return (datetime.now() + timedelta(days=n)).strftime("%Y-%m-%d")

EVENTS = [
    dict(conf_id="n1185515", nid="1185515",
         title="International Trade and Investment Program Meeting, Fall 2026",
         type_name="Program Meeting",
         start_date=d_ahead(3), end_date=d_ahead(4),
         display_date="November 20-21, 2026",
         location="SIEPR, Stanford University",
         organizers="Stephen J. Redding",
         url="https://www.nber.org/conferences/international-trade-and-investment-program-meeting-fall-2026",
         agenda_status="done"),
    dict(conf_id="n1231442", nid="1231442",
         title="SI 2026 International Trade & Investment",
         type_name="Summer Institute Workshop",
         start_date=d_ago(100), end_date=d_ago(98),
         display_date="July 13-15, 2026",
         location="Hotel Marlowe, Cambridge, MA",
         organizers="Treb Allen and Natalia Ramondo",
         url="https://www.nber.org/conferences/si-2026-international-trade-investment",
         agenda_status="done"),
]
for ev in EVENTS:
    conn.execute(
        "INSERT INTO events (conf_id, nid, title, type_name, start_date,"
        " end_date, display_date, location, organizers, url, agenda_status,"
        " first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ev["conf_id"], ev["nid"], ev["title"], ev["type_name"],
         ev["start_date"], ev["end_date"], ev["display_date"],
         ev["location"], ev["organizers"], ev["url"], ev["agenda_status"],
         FIRST_SEEN))

# 未来会议：一篇库内已命中（继承），一篇 bare（无全文）
# 过去会议：一篇 bare
EPAPERS = [
    dict(conf_id="n1185515", pos=0,
         title="A Dynamic Theory of Optimal Tariffs",
         norm_title=db.title_key("A Dynamic Theory of Optimal Tariffs"),
         authors_json='[{"name": "Eduardo Dávila", "aff": "Yale University"},'
                      '{"name": "Andrés Rodríguez-Clare", "aff": "UC Berkeley"}]',
         discussants_json='[{"name": "Mary Amiti", "aff": "FRB New York"}]',
         schedule=f"{d_ahead(3)} 9:15 am", fnum="f241700",
         pdf_url="https://conference.nber.org/conf_papers/f241700/f241700.pdf",
         item_uid=None, journal=None, abstract=None, abstract_zh=None,
         intro_zh=None, title_zh=None, tags_json=None,
         enrich_state="bare"),
    dict(conf_id="n1185515", pos=1,
         title="Export Controls and Semiconductor Supply Chains: Evidence from Recent Restrictions",
         norm_title=db.title_key("Export Controls and Semiconductor Supply Chains: Evidence from Recent Restrictions"),
         authors_json='[{"name": "Treb Allen", "aff": "Yale University"}]',
         discussants_json="[]", schedule=None, fnum="f241701",
         pdf_url="https://conference.nber.org/conf_papers/f241701/f241701.pdf",
         item_uid="nber:w34123",
         journal="",
         abstract="We quantify the effect of export controls.",
         abstract_zh="我们量化了出口管制的效应。",
         intro_zh="量化近期半导体出口管制对供应链的冲击。",
         title_zh="出口管制与半导体供应链：来自近期限制的证据",
         tags_json='["出口管制", "供应链"]',
         enrich_state="matched"),
    dict(conf_id="n1231442", pos=0,
         title="Do Foreigners Pay for Tariffs?",
         norm_title=db.title_key("Do Foreigners Pay for Tariffs?"),
         authors_json='[{"name": "Rodrigo Adão", "aff": "University of Chicago"}]',
         discussants_json="[]", schedule=f"{d_ago(100)} 9:15 am",
         fnum="f241702", pdf_url=None,
         item_uid=None, journal=None, abstract=None, abstract_zh=None,
         intro_zh=None, title_zh=None, tags_json=None,
         enrich_state="bare"),
]
for p in EPAPERS:
    conn.execute(
        "INSERT INTO event_papers (conf_id, pos, title, norm_title,"
        " authors_json, discussants_json, schedule, fnum, pdf_url, item_uid,"
        " journal, abstract, abstract_zh, intro_zh, title_zh, tags_json,"
        " enrich_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (p["conf_id"], p["pos"], p["title"], p["norm_title"],
         p["authors_json"], p["discussants_json"], p["schedule"], p["fnum"],
         p["pdf_url"], p["item_uid"], p["journal"], p["abstract"],
         p["abstract_zh"], p["intro_zh"], p["title_zh"], p["tags_json"],
         p["enrich_state"]))
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
# 顶部关注主题模块：论文标签各计 1 次，推文标签不计入
themes = {t["tag"]: t["n"] for t in payload.get("themes", [])}
checks["主题模块计数正确"] = (
    themes.get("关税") == 1 and themes.get("全球价值链") == 1
    and themes.get("供应链") == 1 and themes.get("方法论") == 1
    and "贸易战" not in themes  # 贸易战只出现在推文标签里
)
checks["主题模块已渲染"] = "近 30 日关注主题" in html and "theme-chip" in html
# 会议板块：payload 结构、即将举行置顶、库内继承、板块入口
events = payload.get("events", [])
checks["会议数据进了 payload"] = len(events) == 2
up = [e for e in events if e["start_date"] > datetime.now().strftime("%Y-%m-%d")]
checks["未来会议在 payload 里"] = len(up) == 1 and up[0]["conf_id"] == "n1185515"
fall = next(e for e in events if e["conf_id"] == "n1185515")
matched = next(p for p in fall["papers"] if p["state"] == "matched")
checks["matched 论文继承标签与简介"] = (
    matched["tags"] == ["出口管制", "供应链"]
    and "出口管制" in matched["intro_zh"]
    and matched["title_zh"].startswith("出口管制"))
checks["matched 论文带工作论文编号"] = matched["wp_num"] == "w34123"
bare = next(p for p in fall["papers"] if p["state"] == "bare")
checks["bare 论文标注暂无全文"] = (
    bare["journal"] == "" and bare["wp_num"] == ""
    and "暂无全文" in html)
si = next(e for e in events if e["conf_id"] == "n1231442")
checks["过去会议论文作者与机构在 payload"] = (
    si["papers"][0]["authors"][0]["aff"] == "University of Chicago")
checks["会议 tab 与计数徽标已渲染"] = (
    "key:'event'" in html and 'id="c-event"' in html)

# 运行时逻辑（tab、分组标签由 JS 生成）：抽取纯函数喂 node 跑真实断言
JS = _re.search(r"<script>\n(.*)</script>", html, _re.S).group(1)

def _grab(name: str) -> str:
    m = (_re.search(rf"function {name}\([\s\S]*?\n\}}", JS)
         or _re.search(rf"const {name} = [^\n]*;", JS))
    if not m:
        raise SystemExit(f"!! 无法从模板抽取 {name}")
    return m.group(0)

js_src = "\n".join(_grab(n) for n in
                   ("WEEK", "state", "fmtDate", "daysAgo", "esc",
                    "rangeLabel", "groupLabel", "matchEvent",
                    "paperRowHTML", "eventCardHTML", "renderEvents"))
node_js = (js_src
           + "\nconst events = "
           + _json.dumps(events, ensure_ascii=False)
           + ";\n"
           + """function tryFilters(){
  const out = {};
  out.n30 = events.filter(matchEvent).length;
  state.range = 365;
  out.n365 = events.filter(matchEvent).length;
  state.q = 'amiti';
  out.qHit = events.filter(matchEvent).length;
  state.q = 'zzzzNoSuchWord';
  out.qMiss = events.filter(matchEvent).length;
  state.q = '';
  const htmlOut = renderEvents(events);
  out.upFirst = htmlOut.indexOf('即将举行') > -1
    && htmlOut.indexOf('即将举行') < htmlOut.indexOf('Do Foreigners Pay');
  out.hasPapers = htmlOut.includes('汇报论文 2 篇');
  out.hasBare = htmlOut.includes('暂无全文');
  return out;
}
console.log(JSON.stringify(tryFilters()));
""")
Path("/tmp/mock_ev_test.js").write_text(node_js, encoding="utf-8")
import subprocess
node_out = subprocess.run(["node", "/tmp/mock_ev_test.js"],
                          capture_output=True, text=True, timeout=30)
if node_out.returncode != 0:
    raise SystemExit(f"!! node 断言脚本失败:\n{node_out.stderr[:500]}")
nr = _json.loads(node_out.stdout)
checks["时间窗过滤:未来会议30天可见,100天前的看不见"] = nr["n30"] == 1 and nr["n365"] == 2
checks["搜索命中点评人与未命中词"] = nr["qHit"] == 1 and nr["qMiss"] == 0
checks["即将举行置顶且渲染论文清单"] = nr["upFirst"] and nr["hasPapers"] and nr["hasBare"]
failed = [k for k, ok in checks.items() if not ok]
if failed:
    print("!! 断言未通过:", failed)
    sys.exit(1)
print("mock 断言全部通过")
