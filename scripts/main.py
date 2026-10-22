#!/usr/bin/env python3
"""每日入口：抓取 → 去重入库 → LLM 摘要与相关性 → 生成网页。

用法:
  python3 scripts/main.py                 # 日常增量，回看 7 天
  python3 scripts/main.py --days 60      # 首次灌数据，回看 60 天
  python3 scripts/main.py --no-llm       # 跳过摘要（只抓取与生成页面）
  python3 scripts/main.py --no-tweets    # 跳过推文抓取
"""
import argparse
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402
from core import summarize  # noqa: E402
from fetchers import nber, scholars, top5, tweets  # noqa: E402


def load_config():
    with open(ROOT / "config" / "scholars.yaml", encoding="utf-8") as f:
        scholars_cfg = yaml.safe_load(f)
    with open(ROOT / "config" / "topics.yaml", encoding="utf-8") as f:
        topics_cfg = yaml.safe_load(f)
    enabled = [s for s in scholars_cfg.get("scholars", [])
               if s.get("enabled", True)]
    return enabled, topics_cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="回看天数")
    ap.add_argument("--no-llm", action="store_true", help="跳过中文摘要")
    ap.add_argument("--no-tweets", action="store_true", help="跳过推文抓取")
    ap.add_argument("--link-limit", type=int, default=30,
                    help="本轮最多新解析多少条推文外链")
    args = ap.parse_args()

    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    print(f"== 贸易学者动向监控 {datetime.now():%Y-%m-%d %H:%M}（回看 {args.days} 天）==")

    scholar_list, topics_cfg = load_config()
    keywords = topics_cfg["trade_keywords"]
    tag_vocab = topics_cfg["tag_vocab"]
    paper_scholars = [s for s in scholar_list
                      if s.get("s2_id") or s.get("openalex_id")]
    tweet_scholars = [s for s in scholar_list if s.get("twitter")]
    print(f"启用学者 {len(scholar_list)} 人"
          f"（论文源 {len(paper_scholars)} 人、推文 {len(tweet_scholars)} 人已配 ID），"
          f"关键词 {len(keywords)} 个")

    conn = db.connect()
    stats = {"new": {}, "llm": 0, "errors": []}

    def run_step(step: str, fn, *a):
        """单个数据源失败不影响其余板块。"""
        try:
            return fn(*a)
        except Exception as e:
            print(f"    ! {step} 本轮失败: {e}")
            stats["errors"].append(step)
            return []

    # 1. Top-5 期刊
    print("[1/4] Top-5 期刊（OpenAlex）")
    for it in run_step("Top-5", top5.fetch, start_date, keywords):
        if db.upsert_item(conn, it):
            stats["new"]["top5"] = stats["new"].get("top5", 0) + 1
    conn.commit()
    print(f"    新增 {stats['new'].get('top5', 0)} 条")

    # 2. NBER
    print("[2/4] NBER 工作论文（OpenAlex NBER 源）")
    for it in run_step("NBER", nber.fetch, start_date, keywords):
        if db.upsert_item(conn, it):
            stats["new"]["nber"] = stats["new"].get("nber", 0) + 1
    conn.commit()
    print(f"    新增 {stats['new'].get('nber', 0)} 条")

    # 3. 学者论文
    print("[3/4] 学者最新论文（OpenAlex，S2 备用）")
    for it in run_step("学者论文", scholars.fetch, start_date, paper_scholars):
        if db.upsert_item(conn, it):
            stats["new"]["scholar"] = stats["new"].get("scholar", 0) + 1
    conn.commit()
    print(f"    新增 {stats['new'].get('scholar', 0)} 条")

    # 4. 学者推文
    if not args.no_tweets:
        print("[4/4] 学者推文（xreach）")
        for it in run_step("推文", tweets.fetch, tweet_scholars, args.days):
            if db.upsert_item(conn, it):
                stats["new"]["tweet"] = stats["new"].get("tweet", 0) + 1
        conn.commit()
        print(f"    新增 {stats['new'].get('tweet', 0)} 条")

        print("[外链] 解析推文里的 t.co 链接")
        from fetchers import links
        n = run_step("外链解析", links.enrich, conn, args.link_limit) or 0
        stats["links"] = n
        print(f"    新解析 {n} 条")

    # 5. LLM 摘要 + 相关性（分批处理，失败的条目本轮跳过避免卡死）
    if not args.no_llm:
        print("[摘要] 生成中文摘要与相关性判断")
        processed = set()
        while True:
            pending = [r for r in db.pending_summary(conn)
                       if r["uid"] not in processed]
            if not pending:
                break
            for row in pending:
                out = summarize.summarize_item(row, tag_vocab)
                if out is None:
                    processed.add(row["uid"])
                    continue
                if out.get("relevant") is False:
                    db.mark_irrelevant(conn, row["uid"])
                    db.save_summary(conn, row["uid"], "（非贸易领域）", [])
                else:
                    summary = out.get("summary_zh", "")
                    if row["source"] == "tweet":
                        # 翻译里不应保留 t.co 短链，页面卡片另有链接
                        summary = re.sub(r"https?://t\.co/\w+", "",
                                         summary).strip()
                    db.save_summary(conn, row["uid"], summary,
                                    out.get("tags", []),
                                    out.get("title_zh", ""))
                processed.add(row["uid"])
                stats["llm"] += 1
                time.sleep(0.3)
            conn.commit()
        print(f"    处理 {stats['llm']} 条")

    # 6. 生成网页
    print("[网页] 生成 docs/index.html")
    from build_site import build
    build(conn, scholar_list)

    db.save_run(conn, stats)
    conn.commit()
    conn.close()
    total = sum(stats["new"].values())
    err = f"，失败板块: {','.join(stats['errors'])}" if stats["errors"] else ""
    print(f"== 完成：新增 {total} 条，摘要 {stats['llm']} 条{err} ==")


if __name__ == "__main__":
    main()
