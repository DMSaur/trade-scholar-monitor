#!/usr/bin/env python3
"""SQLite 状态库：条目去重、摘要缓存、历史归档。"""
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    uid TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    scholar_id TEXT,
    title TEXT,
    authors TEXT,
    venue TEXT,
    url TEXT,
    date TEXT,
    abstract TEXT,
    extra TEXT,
    relevant INTEGER DEFAULT 1,
    summary_zh TEXT,
    tags TEXT,
    first_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_date ON items(date);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE TABLE IF NOT EXISTS runs (
    day TEXT PRIMARY KEY,
    finished_at TEXT,
    stats TEXT
);
CREATE TABLE IF NOT EXISTS link_cache (
    url TEXT PRIMARY KEY,
    final_url TEXT,
    title TEXT,
    domain TEXT,
    image TEXT,
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    conf_id TEXT PRIMARY KEY,
    nid TEXT,
    title TEXT,
    type_name TEXT,
    start_date TEXT,
    end_date TEXT,
    display_date TEXT,
    location TEXT,
    organizers TEXT,
    url TEXT,
    agenda_status TEXT DEFAULT 'pending',
    first_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_date);
CREATE TABLE IF NOT EXISTS event_papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conf_id TEXT NOT NULL,
    pos INTEGER,
    title TEXT,
    norm_title TEXT,
    authors_json TEXT,
    discussants_json TEXT,
    schedule TEXT,
    fnum TEXT,
    pdf_url TEXT,
    slides_url TEXT,
    pnum TEXT,
    item_uid TEXT,
    journal TEXT,
    pub_url TEXT,
    abstract TEXT,
    abstract_zh TEXT,
    intro_zh TEXT,
    title_zh TEXT,
    tags_json TEXT,
    enrich_state TEXT DEFAULT 'new',
    tried_oa INTEGER DEFAULT 0,
    enriched_at TEXT,
    UNIQUE(conf_id, norm_title)
);
CREATE INDEX IF NOT EXISTS idx_event_papers_conf ON event_papers(conf_id);
CREATE INDEX IF NOT EXISTS idx_event_papers_norm ON event_papers(norm_title);
"""


def title_key(title: str) -> str:
    """标题归一化：去符号空格、小写、取前 40 字符，跨版本去重与匹配共用。"""
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (title or "").lower())
    return t[:40]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # 旧库补列（已存在时报错忽略）
    try:
        conn.execute("ALTER TABLE items ADD COLUMN title_zh TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE items ADD COLUMN abstract_zh TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def upsert_item(conn: sqlite3.Connection, item: dict) -> bool:
    """按 uid 去重入库。已存在返回 False，新条目返回 True。"""
    cur = conn.execute(
        "INSERT OR IGNORE INTO items (uid, source, scholar_id, title, authors, venue,"
        " url, date, abstract, extra, relevant, first_seen)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item["uid"],
            item["source"],
            item.get("scholar_id"),
            item.get("title"),
            item.get("authors"),
            item.get("venue"),
            item.get("url"),
            item.get("date"),
            item.get("abstract"),
            json.dumps(item.get("extra") or {}, ensure_ascii=False),
            1 if item.get("relevant", True) else 0,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    return cur.rowcount > 0


def pending_summary(conn: sqlite3.Connection, limit: int = 40) -> list[sqlite3.Row]:
    """取需要生成中文摘要的条目：有 summary_zh 的跳过，relevant=0 的跳过。"""
    return conn.execute(
        "SELECT * FROM items WHERE summary_zh IS NULL AND relevant = 1"
        " ORDER BY date DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_summary(conn: sqlite3.Connection, uid: str, summary_zh: str,
                 tags: list, title_zh: str = "", abstract_zh: str | None = None):
    """abstract_zh 传 None 表示本调用不改动该列（补译循环单独写）。"""
    if abstract_zh is None:
        conn.execute(
            "UPDATE items SET summary_zh = ?, tags = ?, title_zh = ? WHERE uid = ?",
            (summary_zh, json.dumps(tags, ensure_ascii=False), title_zh, uid),
        )
    else:
        conn.execute(
            "UPDATE items SET summary_zh = ?, tags = ?, title_zh = ?, abstract_zh = ?"
            " WHERE uid = ?",
            (summary_zh, json.dumps(tags, ensure_ascii=False), title_zh,
             abstract_zh, uid),
        )


def save_abstract_zh(conn: sqlite3.Connection, uid: str, abstract_zh: str):
    conn.execute("UPDATE items SET abstract_zh = ? WHERE uid = ?",
                 (abstract_zh, uid))


def pending_abstract(conn: sqlite3.Connection,
                     limit: int = 40) -> list[sqlite3.Row]:
    """取需要补译摘要的存量条目：已过摘要流程、无译文的相关论文。"""
    return conn.execute(
        "SELECT * FROM items WHERE relevant = 1 AND source != 'tweet'"
        " AND abstract_zh IS NULL AND summary_zh IS NOT NULL"
        " ORDER BY date DESC LIMIT ?",
        (limit,),
    ).fetchall()


def mark_irrelevant(conn: sqlite3.Connection, uid: str):
    conn.execute("UPDATE items SET relevant = 0 WHERE uid = ?", (uid,))


def items_since(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return conn.execute(
        "SELECT * FROM items WHERE date >= ? AND relevant = 1"
        " ORDER BY date DESC, first_seen DESC",
        (cutoff,),
    ).fetchall()


def save_run(conn: sqlite3.Connection, stats: dict):
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT OR REPLACE INTO runs (day, finished_at, stats) VALUES (?, ?, ?)",
        (today, datetime.now().isoformat(timespec="seconds"),
         json.dumps(stats, ensure_ascii=False)),
    )


def upsert_event(conn: sqlite3.Connection, ev: dict) -> bool:
    """按 conf_id 去重入库；已存在时刷新可变字段（日期/议程状态等）。"""
    cur = conn.execute(
        "INSERT OR IGNORE INTO events (conf_id, nid, title, type_name,"
        " start_date, end_date, display_date, location, organizers, url,"
        " agenda_status, first_seen)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ev["conf_id"],
            ev.get("nid"),
            ev.get("title"),
            ev.get("type_name"),
            ev.get("start_date"),
            ev.get("end_date"),
            ev.get("display_date"),
            ev.get("location"),
            ev.get("organizers"),
            ev.get("url"),
            ev.get("agenda_status", "pending"),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    if cur.rowcount > 0:
        return True
    # 已存在：只补空缺与刷新议程状态（不覆盖既有非空值；议程状态仅显式提供时更新）
    conn.execute(
        "UPDATE events SET nid = COALESCE(nid, ?), title = COALESCE(title, ?),"
        " type_name = COALESCE(type_name, ?), start_date = COALESCE(start_date, ?),"
        " end_date = COALESCE(end_date, ?), display_date = COALESCE(display_date, ?),"
        " location = COALESCE(location, ?), organizers = COALESCE(organizers, ?),"
        " agenda_status = COALESCE(?, agenda_status) WHERE conf_id = ?",
        (
            ev.get("nid"), ev.get("title"), ev.get("type_name"),
            ev.get("start_date"), ev.get("end_date"), ev.get("display_date"),
            ev.get("location"), ev.get("organizers"),
            ev.get("agenda_status"), ev["conf_id"],
        ),
    )
    return False


def upsert_event_paper(conn: sqlite3.Connection, p: dict) -> bool:
    """按 (conf_id, 归一标题) 去重入库。已存在返回 False。"""
    cur = conn.execute(
        "INSERT OR IGNORE INTO event_papers (conf_id, pos, title, norm_title,"
        " authors_json, discussants_json, schedule, fnum, pdf_url, slides_url,"
        " pnum, abstract, enrich_state)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            p["conf_id"],
            p.get("pos"),
            p.get("title"),
            p.get("norm_title"),
            json.dumps(p.get("authors") or [], ensure_ascii=False),
            json.dumps(p.get("discussants") or [], ensure_ascii=False),
            p.get("schedule"),
            p.get("fnum"),
            p.get("pdf_url"),
            p.get("slides_url"),
            p.get("pnum"),
            p.get("abstract"),
            p.get("enrich_state", "new"),
        ),
    )
    return cur.rowcount > 0


def refresh_event_dates(conn: sqlite3.Connection, conf_id: str, papers: list):
    """议程入库后用实际场次日期回填会议起止（比展示日期更准）。"""
    dates = sorted(p.get("schedule", "").split(" ")[0]
                   for p in papers if p.get("schedule"))
    dates = [d for d in dates if d and d != "0000-00-00"]
    if not dates:
        return
    conn.execute(
        "UPDATE events SET start_date = COALESCE(start_date, ?),"
        " end_date = COALESCE(end_date, ?) WHERE conf_id = ?",
        (dates[0], dates[-1], conf_id),
    )


def set_event_agenda_status(conn: sqlite3.Connection, conf_id: str, status: str):
    conn.execute("UPDATE events SET agenda_status = ? WHERE conf_id = ?",
                 (status, conf_id))


def event_papers_to_enrich(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """需要补全的论文：未匹配库内条目、未判死的所有行（新论文与每日重试共用）。"""
    return conn.execute(
        "SELECT * FROM event_papers"
        " WHERE item_uid IS NULL AND norm_title != ''"
        " AND enrich_state NOT IN ('failed')"
        " ORDER BY id"
    ).fetchall()


_EVENT_PAPER_COLS = frozenset({
    "pos", "title", "norm_title", "authors_json", "discussants_json",
    "schedule", "fnum", "pdf_url", "slides_url", "pnum", "item_uid",
    "journal", "pub_url", "abstract", "abstract_zh", "intro_zh", "title_zh",
    "tags_json", "enrich_state", "tried_oa",
})


def update_event_paper(conn: sqlite3.Connection, pid: int, **fields):
    """按列名更新 event_papers（白名单外键静默忽略，防调用方键名漂移）。"""
    fields = {k: v for k, v in fields.items() if k in _EVENT_PAPER_COLS}
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE event_papers SET {cols}, enriched_at = ? WHERE id = ?",
        (*fields.values(), datetime.now().isoformat(timespec="seconds"), pid),
    )


def events_recent(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    """展示窗口内的会议：过去 days 天 + 全部未来会议（未来日期必然大于窗口起点）。"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return conn.execute(
        "SELECT * FROM events"
        " WHERE start_date IS NULL OR start_date >= ?"
        " ORDER BY COALESCE(start_date, '9999') DESC",
        (cutoff,),
    ).fetchall()


def papers_by_confs(conn: sqlite3.Connection, conf_ids: list) -> list[sqlite3.Row]:
    if not conf_ids:
        return []
    marks = ",".join("?" * len(conf_ids))
    return conn.execute(
        f"SELECT * FROM event_papers WHERE conf_id IN ({marks})"
        " ORDER BY conf_id, pos, id",
        conf_ids,
    ).fetchall()
