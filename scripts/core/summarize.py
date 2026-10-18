#!/usr/bin/env python3
"""中文摘要与主题标签：DashScope（通义千问，OpenAI 兼容接口）。

每条论文或推文生成一句中文摘要加标签。top5 与 NBER 条目同时让模型确认
是否属于贸易领域。按条目缓存：已有 summary_zh 的不再调用。
"""
import json
import os
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent.parent

MODEL = os.environ.get("MONITOR_LLM_MODEL", "qwen-flash")

_client = None
_disabled = False  # 熔断：连续失败达到阈值后本轮停用
FAIL_LIMIT = 3
_fail_streak = 0


def _load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def client() -> OpenAI | None:
    global _client
    if _client is None:
        _load_env()
        key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not key:
            print("    ! 未配置 DASHSCOPE_API_KEY，跳过摘要生成")
            return None
        _client = OpenAI(
            api_key=key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    return _client


PAPER_PROMPT = """你是国际经济学研究助理。判断下面的经济学论文是否属于国际贸易领域（广义：贸易、关税、全球价值链、供应链、贸易政策、贸易与劳动力、汇率与贸易、制裁与出口管制、经济地理等）。

标题：{title}
作者：{authors}
期刊：{venue}
摘要：{abstract}

严格输出 JSON（不要 markdown 代码块）：
{{"relevant": true/false, "summary_zh": "一句话中文摘要，不超过60字，概括问题、方法与核心发现", "tags": ["从下方标签表中选1-3个"]}}

标签表：{tags}"""

TWEET_PROMPT = """你是国际经济学研究助理。为下面一位贸易学者的推文写摘要。

作者：{authors}
推文原文：{text}

严格输出 JSON（不要 markdown 代码块）：
{{"summary_zh": "一句话中文摘要，不超过60字，保留关键数据与观点", "tags": ["从下方标签表中选0-3个"]}}

标签表：{tags}"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError(f"无 JSON: {text[:100]}")
    return json.loads(text[start:end + 1])


def summarize_item(row, tag_vocab: list) -> dict | None:
    """返回 {'relevant': bool|None, 'summary_zh': str, 'tags': [str]} 或 None（失败）。"""
    global _disabled, _fail_streak
    if _disabled:
        return None
    c = client()
    if c is None:
        _disabled = True
        return None
    tags = "、".join(tag_vocab)
    if row["source"] == "tweet":
        prompt = TWEET_PROMPT.format(
            authors=row["authors"], text=row["abstract"][:1500], tags=tags)
    else:
        prompt = PAPER_PROMPT.format(
            title=row["title"] or "（无标题）",
            authors=row["authors"] or "",
            venue=row["venue"] or "",
            abstract=(row["abstract"] or "（无摘要）")[:3000],
            tags=tags,
        )
    try:
        resp = c.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        out = _parse_json(resp.choices[0].message.content or "")
        valid = set(tag_vocab) | {"其他"}
        out["tags"] = [t for t in out.get("tags", []) if t in valid][:3]
        _fail_streak = 0
        return out
    except Exception as e:
        _fail_streak += 1
        if _fail_streak >= FAIL_LIMIT:
            _disabled = True
            print(f"    ! LLM 连续失败 {_fail_streak} 次，本轮停用摘要"
                  f"（最后错误: {e}）")
        else:
            print(f"    ! 摘要失败 {row['uid']}: {e}")
        return None
