#!/usr/bin/env python3
"""NBER 会议与研讨会追踪（国际板块）。

数据通路（2026-10 实测，均为公开接口/静态页，无需登录）：
- 会议列表: GET /api/v1/conference_listing/contentType/conference/_/_/search
            ?eventType=upcoming|past&perPage=100&page=N（page 从 0 起）
- 会议议程: GET /api/conference/{nid}/agenda
            论文条目自带标题/摘要/作者机构/点评人/NBER 编号/论文 PDF 地址
- 详情页:   静态 HTML，page-header 里有 DATE/LOCATION/ORGANIZER 标记

补全层级（event_papers.enrich_state）：
  matched  命中库内条目（工作论文编号直连或归一标题匹配），继承摘要与标签
  oa       OpenAlex 按标题反查命中（每篇只试一次），记期刊版信息或摘要
  pdf      下载论文 PDF 抽前几页文本，LLM 生成中文简介与标签
  bare     无任何材料，只展示标题作者，等工作论文版出现后每日自动回填

conf_id 统一用 "n"+Drupal nid（列表接口就有，不依赖议程是否已放出）。
"""
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402
from core import summarize  # noqa: E402
from fetchers import openalex_common  # noqa: E402

LIST_API = ("https://www.nber.org/api/v1/conference_listing"
            "/contentType/conference/_/_/search")
AGENDA_API = "https://www.nber.org/api/conference/{nid}/agenda"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PROXY = os.environ.get("NBER_PROXY", "http://127.0.0.1:7897")

DISCOVERY_WINDOW = 365          # 往回找多少天的已开会会议
MAX_PAST_PAGES = 40             # 首次回填一年的上限页数（每页 100 场）
AGENDA_RETRY_DAYS = 120         # 开会超过这么多天的未公开议程不再重试
MAX_OA_LOOKUPS = 100            # 每轮 OpenAlex 反查上限
MAX_TRANSLATIONS = 30           # 每轮摘要翻译上限

# 配置缺省时的会议名称匹配模式（小写子串），可在 topics.yaml event_programs 覆盖
DEFAULT_PATTERNS = [
    "international trade", "trade & investment", "trade and investment",
    "trade & macro", "trade and macro", "tariff", "trade policy",
    "international finance", "international economics", "geopolitics",
    "across borders",
]

# 判断 venue 是否像工作论文版（期刊版信息优先展示）
_WP_HINTS = ("nber", "bureau", "ssrn", "working paper", "workshop",
             "university", "institute", "报告", "预印本", "reprint")


# ---------------- HTTP ----------------

def _get(url, params=None, max_retry=6):
    """nber.org 直连优先，失败切本机代理（与 OpenAlex 相反：本站不被墙）。"""
    last = "未知错误"
    for attempt in range(max_retry):
        use_proxy = bool(attempt % 2)
        try:
            r = requests.get(
                url, params=params, headers={"User-Agent": _UA}, timeout=40,
                proxies={"http": PROXY, "https": PROXY} if use_proxy else None)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code == 404:
                return None
        except requests.RequestException as e:
            last = str(e)[:120]
        time.sleep(min(3 * (attempt + 1), 15))
    raise RuntimeError(f"GET {url} 失败: {last}")


def _get_json(url, params=None):
    r = _get(url, params)
    return r.json() if r is not None else None


def _download(url, cap=8 * 1024 * 1024):
    """流式下载，超限返回 None（太大的 PDF 不值得为其花 LLM 额度）。"""
    for use_proxy in (False, True):
        try:
            with requests.get(
                    url, headers={"User-Agent": _UA}, timeout=60, stream=True,
                    proxies={"http": PROXY, "https": PROXY} if use_proxy else None) as r:
                r.raise_for_status()
                buf = b""
                for chunk in r.iter_content(65536):
                    buf += chunk
                    if len(buf) > cap:
                        return None
                return buf
        except requests.RequestException:
            continue
    return None


# ---------------- 发现 ----------------

def _parse_displaydate(s: str):
    """'July 13-15, 2026' / 'November 20, 2026' → 起始日 ISO 串。"""
    m = re.match(r"([A-Za-z]+)\s+(\d+)(?:\s*[-–]\s*\d+)?,?\s+(\d{4})",
                 (s or "").strip())
    if not m:
        return None
    try:
        return datetime.strptime(
            f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        return None


def discover(conn, patterns: list, window_days: int = DISCOVERY_WINDOW) -> list:
    """列表接口找窗口内名称命中的会议，返回按开始日期倒序的候选列表。"""
    cutoff = (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    # past 流按时间倒序：翻到比库里最新一场还早 14 天即可停（日常只拉增量页）
    row = conn.execute("SELECT MAX(start_date) FROM events").fetchone()
    newest = row[0] if row else None
    stop_at = None
    if newest:
        stop_at = (datetime.strptime(newest, "%Y-%m-%d")
                   - timedelta(days=14)).strftime("%Y-%m-%d")
    found: dict = {}
    for event_type in ("upcoming", "past"):
        max_pages = MAX_PAST_PAGES if event_type == "past" else 2
        for page in range(1, max_pages + 1):    # 接口分页从 1 起，page=0 返回空
            d = _get_json(LIST_API, {"eventType": event_type,
                                     "perPage": 100, "page": page}) or {}
            results = d.get("results") or []
            if not results:
                break
            oldest = None
            for r in results:
                date = _parse_displaydate(r.get("displaydate"))
                if date and (oldest is None or date < oldest):
                    oldest = date
                if event_type == "past" and date and date < cutoff:
                    continue
                title = (r.get("title") or "").strip()
                low = title.lower()
                if not any(p in low for p in patterns):
                    continue
                nid = str(r.get("nid") or "")
                if nid and nid not in found:
                    found[nid] = {
                        "nid": nid,
                        "title": title,
                        "url": "https://www.nber.org" + (r.get("url") or ""),
                        "type_name": r.get("conferenceTypeName") or "",
                        "display_date": (r.get("displaydate") or "").strip(),
                    }
            if event_type == "past" and oldest:
                if stop_at and oldest < stop_at:
                    break
                if oldest < cutoff:
                    break
    return sorted(found.values(),
                  key=lambda x: _parse_displaydate(x["display_date"]) or "",
                  reverse=True)


def fetch_detail(url: str) -> dict:
    """详情页静态 HTML 里的 DATE/LOCATION/ORGANIZER。"""
    r = _get(url)
    if r is None:
        return {}
    out = {}
    for key, field in (("DATE", "display_date"), ("LOCATION", "location"),
                       ("ORGANIZER", "organizers")):
        m = re.search(rf'citation-item-label">\s*{key}\s*</span>\s*([^<]+)',
                      r.text)
        if m:
            out[field] = re.sub(r"\s+", " ", m.group(1)).strip()
    return out


# ---------------- 议程 ----------------

def _clean_abstract(raw, title: str):
    """议程里的摘要字段；作者只交标题时是占位串，归为无摘要。"""
    if not raw:
        return None
    text = re.sub(r"<[^>]+>", " ", str(raw))
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        text = text.replace(a, b)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text == (title or "").strip():
        return None
    return text


def fetch_agenda(nid: str):
    """拉议程 JSON。返回 (papers, status)；status ∈ done/empty/none/failed。"""
    try:
        d = _get_json(AGENDA_API.format(nid=nid))
    except RuntimeError:
        return [], "failed"
    if not isinstance(d, dict):
        return [], "failed"
    if d.get("access_by_user"):
        return [], "none"       # 闭门会议，无公开议程
    papers = []
    for it in d.get("items") or []:
        if not isinstance(it, dict):
            continue
        p = it.get("paper")
        if not isinstance(p, dict):
            continue
        rec = p.get("record") or {}
        if (p.get("class") or rec.get("class")) == "break":
            continue
        title = (rec.get("title") or "").strip()
        if not title:
            continue
        # 场次时间在条目包装层：wrapper.record.schedule_date + schedule_time_display
        wrap_rec = it.get("record") or {}
        sdate = (wrap_rec.get("schedule_date") or p.get("schedule_date")
                 or rec.get("schedule_date") or "")
        stime = (it.get("schedule_time_display") or p.get("schedule_time")
                 or "")
        room = (wrap_rec.get("room") or p.get("room") or "").strip()
        schedule = " ".join(x for x in (sdate, stime, room) if x).strip()
        authors = []
        for a in p.get("author_with_objs_array") or []:
            name = (a.get("name")
                    or f"{a.get('first', '')} {a.get('last', '')}").strip()
            aff = ((a.get("obj") or {}).get("univaffil_and_nber") or "").strip()
            if name:
                authors.append({"name": name, "aff": aff})
        discussants = []
        for du in p.get("discussant_struct") or []:
            u = du.get("user") or {}
            name = (u.get("fullname") or "").strip()
            if name:
                discussants.append({"name": name,
                                    "aff": (u.get("univaffil_and_nber")
                                            or "").strip()})
        papers.append({
            "title": title,
            "norm_title": db.title_key(title),
            "authors": authors,
            "discussants": discussants,
            "schedule": schedule or None,
            "fnum": (rec.get("paper") or "").strip() or None,
            "pdf_url": (p.get("conference_program_paper_url")
                        or "").strip() or None,
            "slides_url": (p.get("slides_url") or "").strip() or None,
            "pnum": (p.get("conf_presented_pnum") or "").strip() or None,
            "abstract": _clean_abstract(rec.get("abstract"), title),
        })
    return papers, ("done" if papers else "empty")


# ---------------- 补全 ----------------

def _items_index(conn) -> dict:
    idx = {}
    for r in conn.execute(
            "SELECT uid, title FROM items WHERE relevant = 1 AND title != ''"):
        k = db.title_key(r["title"])
        if k:
            idx.setdefault(k, []).append(r["uid"])
    return idx


def _prefer_journal(conn, uids: list):
    """同题多个库内条目时优先期刊版（venue 不像工作论文的排前）。"""
    def wpness(uid):
        r = conn.execute("SELECT venue FROM items WHERE uid = ?",
                         (uid,)).fetchone()
        v = (r["venue"] if r else "").lower()
        return any(h in v for h in _WP_HINTS)
    return sorted(uids, key=wpness)[0]


def _inherit(item_row) -> dict:
    """从库内条目继承展示字段。"""
    extra = json.loads(item_row["extra"] or "{}")
    keys = item_row.keys()
    journal = extra.get("journal_short") or ""
    venue = item_row["venue"] or ""
    if not journal and venue and not any(h in venue.lower() for h in _WP_HINTS):
        journal = venue
    return {
        "item_uid": item_row["uid"],
        "abstract": (item_row["abstract"] or "") or None,
        "abstract_zh": (item_row["abstract_zh"] if "abstract_zh" in keys
                        else "") or None,
        "intro_zh": item_row["summary_zh"] or None,
        "title_zh": (item_row["title_zh"] if "title_zh" in keys else "") or None,
        "tags_json": item_row["tags"] or None,
        "journal": journal or None,
        "pub_url": item_row["url"] or None,
        "enrich_state": "matched",
    }


def _oa_lookup(title: str):
    """OpenAlex 按标题精确反查。返回 (journal, pub_url, abstract) 或 None。

    只接受归一标题完全一致的命中（社区教训：模糊匹配会配到同名论文）。
    """
    safe = re.sub(r"\s+", " ",
                  re.sub(r"[^A-Za-z0-9 ]+", " ", title)).strip()
    if len(safe) < 15:
        return None
    d = openalex_common.get("/works", {"filter": f"title.search:{safe}",
                                       "per-page": 5})
    works = (d or {}).get("results") or []
    k = db.title_key(title)
    exact = [w for w in works
             if db.title_key(w.get("display_name") or "") == k]
    if not exact:
        return None
    journal = pub_url = None
    abstract = None
    for w in exact:
        src = ((w.get("primary_location") or {}).get("source") or {})
        if (not journal and src.get("type") == "journal"
                and src.get("display_name")):
            journal = src["display_name"]
        if not pub_url:
            pub_url = (w.get("doi") or w.get("doi_url")
                       or w.get("landing_page_url") or w.get("id"))
        if not abstract and w.get("abstract_inverted_index"):
            abstract = openalex_common.inverted_abstract(
                w["abstract_inverted_index"])
    return journal, pub_url, (abstract or None)


def _pdf_text(pdf_url: str):
    """下载论文 PDF，抽前 3 页文本（截 6000 字符）供 LLM 概括。"""
    buf = _download(pdf_url)
    if not buf:
        return None
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(buf))
        text = ""
        for page in reader.pages[:3]:
            text += page.extract_text() or ""
            if len(text) > 6000:
                break
        text = re.sub(r"\s+", " ", text).strip()
        return text[:6000] or None
    except Exception as e:
        print(f"    ! PDF 抽文本失败 {pdf_url}: {e}")
        return None


def enrich(conn, tag_vocab: list, pdf_limit: int = 10, use_llm: bool = True):
    """论文补全：库内匹配（免费，每日重试）→ OpenAlex 一次 → PDF 简介。"""
    rows = db.event_papers_to_enrich(conn)
    if not rows:
        return
    idx = _items_index(conn)
    n_pdf = n_oa = n_trans = 0
    for row in rows:
        pid = row["id"]
        upd: dict = {}
        # 1) 工作论文编号直连库内条目
        pnum = (row["pnum"] or "").lower()
        if pnum and re.fullmatch(r"w\d+", pnum):
            it = conn.execute("SELECT * FROM items WHERE uid = ?",
                              (f"nber:{pnum}",)).fetchone()
            if it:
                upd = _inherit(it)
        # 2) 归一标题匹配（新工作论文入库后每日免费重试，逐步升级）
        if not upd:
            uids = idx.get(row["norm_title"]) or []
            if uids:
                it = conn.execute("SELECT * FROM items WHERE uid = ?",
                                  (_prefer_journal(conn, uids),)).fetchone()
                if it:
                    upd = _inherit(it)
        # 3) OpenAlex 反查（每篇一次）
        abstract = row["abstract"]
        if not upd and not row["tried_oa"] and n_oa < MAX_OA_LOOKUPS:
            try:
                oa = _oa_lookup(row["title"])
            except Exception as e:
                print(f"    ! OpenAlex 反查失败 {row['title'][:40]}: {e}")
                oa = None
                time.sleep(2)
            upd["tried_oa"] = 1
            if oa:
                journal, pub_url, oa_abs = oa
                upd["journal"] = journal
                upd["pub_url"] = pub_url
                if oa_abs and not abstract:
                    abstract = oa_abs
                    upd["abstract"] = oa_abs
                n_oa += 1
        # 4) LLM 元数据：有真实摘要用摘要，否则抽 PDF。
        #    tags_json 写入（哪怕空数组）即视为已尝试，简介为空不日日重跑
        need_meta = use_llm and not row["tags_json"]
        if need_meta:
            authors = "、".join(
                a["name"] for a in json.loads(row["authors_json"] or "[]"))
            if abstract:
                meta = summarize.event_paper_meta(
                    row["title"], authors, abstract, tag_vocab)
                if meta:
                    meta["tags_json"] = meta.pop("tags")
                    upd.update(meta)
            # 有的作者把 conference_program_paper_url 填成网盘页（非 PDF 文件），
            # 只对真正的 .pdf 地址做下载，其余留 bare 等库内匹配
            elif (row["pdf_url"] and ".pdf" in row["pdf_url"].lower()
                  and n_pdf < pdf_limit):
                text = _pdf_text(row["pdf_url"])
                if text:
                    meta = summarize.event_pdf_meta(
                        row["title"], authors, text, tag_vocab)
                    if meta:
                        meta["tags_json"] = meta.pop("tags")
                        upd.update(meta)
                    n_pdf += 1
        # 摘要全文翻译（有英文摘要而缺中文时；matched 论文继承库内译文）
        if (use_llm and abstract and not upd.get("abstract_zh")
                and not row["abstract_zh"] and n_trans < MAX_TRANSLATIONS):
            try:
                upd["abstract_zh"] = summarize.translate_abstract(abstract)
                n_trans += 1
            except Exception:
                pass    # 失败留 NULL 下轮重试
        # 兜底状态：matched 之外按材料来源标注，全部保留每日免费重试资格
        if not upd.get("enrich_state"):
            if abstract:
                upd["enrich_state"] = "oa"
            elif upd.get("intro_zh"):
                upd["enrich_state"] = "pdf"
            else:
                upd["enrich_state"] = "bare"
        db.update_event_paper(conn, pid, **upd)
    matched = conn.execute(
        "SELECT COUNT(*) FROM event_papers WHERE enrich_state = 'matched'"
    ).fetchone()[0]
    print(f"    补全：库内命中 {matched}，本轮 OpenAlex {n_oa}、"
          f"PDF 简介 {n_pdf}、摘要翻译 {n_trans}")


# ---------------- 入口 ----------------

def run(conn, topics_cfg: dict, pdf_limit: int = 10, use_llm: bool = True):
    """每日任务：发现会议 → 抓详情与议程 → 补全论文。返回 (新会议数, 新论文数)。"""
    patterns = [str(p).lower() for p in
                (topics_cfg.get("event_programs") or DEFAULT_PATTERNS)]
    n_ev = n_pp = 0
    # 1) 发现（新会议补详情页信息）
    for cand in discover(conn, patterns):
        conf_id = f"n{cand['nid']}"
        is_new = db.upsert_event(conn, {
            "conf_id": conf_id,
            "nid": cand["nid"],
            "title": cand["title"],
            "type_name": cand["type_name"],
            "display_date": cand["display_date"],
            # 议程未放出时先用列表展示日期兜底，议程到手后以实际场次日期为准
            "start_date": _parse_displaydate(cand["display_date"]),
            "url": cand["url"],
        })
        if is_new:
            n_ev += 1
            detail = fetch_detail(cand["url"])
            if detail:
                db.upsert_event(conn, {"conf_id": conf_id, **detail})
            print(f"    + 会议 {cand['display_date']} {cand['title']}")
    conn.commit()
    # 2) 议程：从没抓过的必须抓一次（不论多老）；已抓过但空的只对近期/未来会议重试
    cutoff = (datetime.now() - timedelta(days=AGENDA_RETRY_DAYS)
              ).strftime("%Y-%m-%d")
    pending = conn.execute(
        "SELECT * FROM events WHERE agenda_status = 'pending'"
        " OR (agenda_status IN ('empty','none','failed')"
        " AND (start_date IS NULL OR start_date >= ?))", (cutoff,)
    ).fetchall()
    for ev in pending:
        papers, status = fetch_agenda(ev["nid"])
        if status == "failed":
            continue    # 网络问题，下轮再试，不写状态
        for i, p in enumerate(papers):
            p["conf_id"] = ev["conf_id"]
            p["pos"] = i
            if db.upsert_event_paper(conn, p):
                n_pp += 1
        if papers:
            db.refresh_event_dates(conn, ev["conf_id"], papers)
        db.set_event_agenda_status(conn, ev["conf_id"], status)
        if papers:
            print(f"    + 议程 {ev['title'][:40]}：{len(papers)} 篇")
        time.sleep(0.5)
    conn.commit()
    # 3) 补全
    enrich(conn, topics_cfg.get("tag_vocab") or [],
           pdf_limit=pdf_limit, use_llm=use_llm)
    conn.commit()
    return n_ev, n_pp
