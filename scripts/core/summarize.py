#!/usr/bin/env python3
"""中文摘要与主题标签：DeepSeek（Anthropic 兼容接口）。

每条论文生成中文标题翻译、一句摘要和标签；推文生成摘要和标签。
top5 与 NBER 条目同时让模型确认是否属于贸易领域。
按条目缓存：已有 summary_zh 的不再调用。凭据见项目 .env。
"""
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent.parent

BASE_URL = os.environ.get(
    "ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic").rstrip("/")
AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
MODEL = os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-flash")

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
    global BASE_URL, AUTH_TOKEN, MODEL
    BASE_URL = os.environ.get(
        "ANTHROPIC_BASE_URL", BASE_URL).rstrip("/")
    AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", AUTH_TOKEN).strip()
    MODEL = os.environ.get("ANTHROPIC_MODEL", MODEL)


def available() -> bool:
    _load_env()
    return bool(AUTH_TOKEN)


def _chat(prompt: str, max_tokens: int = 800) -> str:
    r = requests.post(
        f"{BASE_URL}/v1/messages",
        headers={
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=90,
    )
    r.raise_for_status()
    parts = [b.get("text", "") for b in r.json().get("content", [])
             if b.get("type") == "text"]
    return "".join(parts)


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


PAPER_PROMPT = """你是国际经济学研究助理。判断下面的经济学论文是否属于国际贸易领域（广义：贸易、关税、全球价值链、供应链、贸易政策、贸易与劳动力、汇率与贸易、制裁与出口管制、经济地理等）。

标题：{title}
作者：{authors}
期刊：{venue}
摘要：{abstract}

严格输出 JSON（不要 markdown 代码块）：
{{"relevant": true/false, "title_zh": "论文标题的中文翻译，简洁准确", "summary_zh": "一句话中文摘要，不超过60字，概括问题、方法与核心发现", "tags": ["从下方标签表中选1-3个"]}}

标签表：{tags}"""

TWEET_PROMPT = """你是国际经济学研究助理。把下面这条推文完整翻译成中文。

作者：{authors}
推文原文：{text}

要求：忠实翻译全文，不概括、不省略、不添加解释；保留数字、人名与原文语气；专有名词首次出现时可括注英文。

严格输出 JSON（不要 markdown 代码块）：
{{"translation_zh": "完整中文翻译", "tags": ["从下方标签表中选0-3个"]}}

标签表：{tags}"""


def summarize_item(row, tag_vocab: list) -> dict | None:
    """返回含 relevant/title_zh/summary_zh/tags 的字典，或 None（失败）。"""
    global _disabled, _fail_streak
    if _disabled:
        return None
    _load_env()
    if not AUTH_TOKEN:
        print("    ! 未配置 ANTHROPIC_AUTH_TOKEN，停用摘要")
        _disabled = True
        return None
    tags = "、".join(tag_vocab)
    max_tokens = 2000
    if row["source"] == "tweet":
        prompt = TWEET_PROMPT.format(
            authors=row["authors"], text=row["abstract"][:2500], tags=tags)
    else:
        max_tokens = 800
        prompt = PAPER_PROMPT.format(
            title=row["title"] or "（无标题）",
            authors=row["authors"] or "",
            venue=row["venue"] or "",
            abstract=(row["abstract"] or "（无摘要）")[:3000],
            tags=tags,
        )
    try:
        out = _parse_json(_chat(prompt, max_tokens=max_tokens))
        valid = set(tag_vocab) | {"其他"}
        out["tags"] = [t for t in out.get("tags", []) if t in valid][:3]
        out["title_zh"] = (out.get("title_zh") or "").strip()
        out["summary_zh"] = (out.get("translation_zh")
                             or out.get("summary_zh") or "").strip()
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
