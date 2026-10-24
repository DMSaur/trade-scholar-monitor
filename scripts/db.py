#!/usr/bin/env python3
"""SQLite 状态库：条目去重、摘要缓存、历史归档。"""
import json
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
"""


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
