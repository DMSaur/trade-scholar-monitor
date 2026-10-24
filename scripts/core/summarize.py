#!/usr/bin/env python3
"""中文摘要与主题标签：DeepSeek（Anthropic 兼容接口）。

每条论文生成中文标题翻译、一句摘要和标签；推文生成摘要和标签。
top5 与 NBER 条目同时让模型确认是否属于贸易领域。
按条目缓存：已有 summary_zh 的不再调用。凭据见项目 .env。
"""
import json
import os
import re
import time
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


_RETRY_STATUS = (429, 500, 502, 503, 504)
_MAX_TOKENS_CAP = 8000


def _chat_once(prompt: str, max_tokens: int) -> tuple[str, str]:
    """单次请求，返回 (正文, stop_reason)；限流、网关错误、空响应内部重试。"""
    last_err = "未知错误"
    for attempt in range(3):
        if attempt:
            time.sleep(3 * attempt)
        try:
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
            if r.status_code in _RETRY_STATUS:
                last_err = f"HTTP {r.status_code}"
                continue
            r.raise_for_status()
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if b.get("type") == "text").strip()
            if text:
                return text, data.get("stop_reason") or ""
            last_err = "空响应"
        except (requests.RequestException, ValueError) as e:
            last_err = str(e)[:120]
    raise RuntimeError(last_err)


def _chat(prompt: str, max_tokens: int = 800) -> str:
    """输出被 max_tokens 掐断时自动翻倍上限重试一次（模型思考占额度）。"""
    text, stop = _chat_once(prompt, max_tokens)
    if stop == "max_tokens" and max_tokens < _MAX_TOKENS_CAP:
        bigger = min(max_tokens * 2, _MAX_TOKENS_CAP)
        print(f"    ~ 输出触到 max_tokens({max_tokens})，提到 {bigger} 重试")
        try:
            text2, stop2 = _chat_once(prompt, bigger)
            if stop2 != "max_tokens" or len(text2) > len(text):
                return text2
        except RuntimeError:
            pass  # 加大额度的重试失败时退回首次结果，走截断抢救
    return text


def _json_unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


_STR_KEYS = ("title_zh", "summary_zh", "translation_zh", "abstract_zh",
             "translation")


def _salvage_fields(text: str) -> dict:
    """截断 JSON 的兜底解析：逐字段正则提取，容忍值被截断在半路。"""
    out = {}
    m = re.search(r'"relevant"\s*:\s*(true|false)', text, re.I)
    if m:
        out["relevant"] = m.group(1).lower() == "true"
    for key in _STR_KEYS:
        m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)', text)
        if m and m.group(1).strip():
            out[key] = _json_unescape(m.group(1)).strip()
    m = re.search(r'"tags"\s*:\s*\[(.*?)\]', text, re.S)
    if m:
        out["tags"] = [_json_unescape(t) for t in
                       re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))]
    return out


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass  # 截断或格式破损，走字段级兜底
    salvaged = _salvage_fields(text)
    if salvaged.get("relevant") is not None or any(
            salvaged.get(k) for k in _STR_KEYS):
        return salvaged
    raise ValueError(f"无 JSON: {text[:100]}")


PAPER_PROMPT = """你是国际经济学研究助理。判断下面的经济学论文是否属于国际贸易领域（广义：贸易、关税、全球价值链、供应链、贸易政策、贸易与劳动力、汇率与贸易、制裁与出口管制、经济地理等）。

标题：{title}
作者：{authors}
期刊：{venue}
摘要：{abstract}

严格输出 JSON（不要 markdown 代码块）：
{{"relevant": true/false, "title_zh": "论文标题的中文翻译，简洁准确", "summary_zh": "一句话中文摘要，不超过60字，概括问题、方法与核心发现", "abstract_zh": "英文摘要的完整中文翻译，忠实全文不概括不省略；摘要为空时输出空字符串", "tags": ["从下方标签表中选1-3个"]}}

标签表：{tags}"""

TRANSLATE_PROMPT = """你是国际经济学论文翻译。把下面的英文摘要片段完整翻译成中文（它是整篇摘要的第 {part} 部分、共 {total} 部分，前后文可能不完整，直接翻译所见内容即可）。

{chunk}

要求：忠实原文，不概括、不省略、不添加解释；保留数字与专有名词；术语用经济学标准中文译法。

严格输出 JSON（不要 markdown 代码块）：
{{"translation": "这段文字的完整中文翻译"}}"""

TWEET_PROMPT = """你是国际经济学研究助理。把下面这条推文完整翻译成中文。

作者：{authors}
推文原文：{text}

要求：忠实翻译全文，不概括、不省略、不添加解释；保留数字、人名与原文语气；专有名词首次出现时可括注英文。

严格输出 JSON（不要 markdown 代码块）：
{{"translation_zh": "完整中文翻译", "tags": ["从下方标签表中选0-3个"]}}

标签表：{tags}"""

EVENT_PAPER_PROMPT = """你是国际经济学研究助理。下面是一场 NBER 会议汇报论文的信息。

标题：{title}
作者：{authors}
摘要：{abstract}

严格输出 JSON（不要 markdown 代码块）：
{{"title_zh": "论文标题的中文翻译，简洁准确", "intro_zh": "两三句中文简介，概括研究问题、方法与核心发现，不超过100字", "tags": ["从下方标签表中选1-3个"]}}

标签表：{tags}"""

EVENT_PDF_PROMPT = """你是国际经济学研究助理。下面是从一篇 NBER 会议汇报论文 PDF 抽取的文本片段，可能乱序、缺页或含页眉页脚。

标题：{title}
作者：{authors}
文本片段：{text}

根据文本判断这篇论文研究什么。严格输出 JSON（不要 markdown 代码块）：
{{"title_zh": "论文标题的中文翻译，简洁准确", "intro_zh": "两三句中文简介，概括研究问题、方法与核心发现，不超过100字；文本不足以判断时输出空字符串", "tags": ["从下方标签表中选1-3个"]}}

标签表：{tags}"""


_ABS_CHUNK = 1200  # 单块字符数上限：块小则单次输出小，远离截断风险


def _chunk_abstract(text: str, cap: int = _ABS_CHUNK) -> list[str]:
    """按句子边界切块；超长单句硬切，保证每块不超过 cap。"""
    chunks, cur = [], ""
    for sent in re.split(r'(?<=[.!?])\s+', text.strip()):
        if not sent.strip():
            continue
        while len(sent) > cap:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(sent[:cap])
            sent = sent[cap:]
        if len(cur) + len(sent) + 1 > cap:
            chunks.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def translate_abstract(abstract: str) -> str:
    """分块翻译英文摘要，拼接为完整中文译文；失败抛异常留待下轮重试。"""
    global _disabled, _fail_streak
    if _disabled:
        raise RuntimeError("LLM 已熔断")
    _load_env()
    if not AUTH_TOKEN:
        raise RuntimeError("未配置 ANTHROPIC_AUTH_TOKEN")
    chunks = _chunk_abstract(abstract)
    parts = []
    try:
        for i, chunk in enumerate(chunks, 1):
            prompt = TRANSLATE_PROMPT.format(
                part=i, total=len(chunks), chunk=chunk)
            out = _parse_json(_chat(prompt, max_tokens=3000))
            part = (out.get("translation") or "").strip()
            if not part:
                raise RuntimeError(f"第 {i}/{len(chunks)} 块译文为空")
            parts.append(part)
        _fail_streak = 0
    except Exception:
        _fail_streak += 1
        if _fail_streak >= FAIL_LIMIT:
            _disabled = True
            print("    ! LLM 连续失败达到阈值，本轮停用翻译")
        raise
    return "".join(parts)


def _event_meta(prompt: str, tag_vocab: list) -> dict | None:
    """会议论文元数据公共出口：解析 + 标签过滤 + 熔断计数。"""
    global _disabled, _fail_streak
    if _disabled:
        return None
    _load_env()
    if not AUTH_TOKEN:
        print("    ! 未配置 ANTHROPIC_AUTH_TOKEN，停用会议论文简介")
        _disabled = True
        return None
    try:
        out = _parse_json(_chat(prompt, max_tokens=2000))
        valid = set(tag_vocab) | {"其他"}
        out["tags"] = json.dumps(
            [t for t in out.get("tags", []) if t in valid][:3],
            ensure_ascii=False)
        out["title_zh"] = (out.get("title_zh") or "").strip()
        out["intro_zh"] = (out.get("intro_zh")
                           or out.get("summary_zh") or "").strip()
        _fail_streak = 0
        return out
    except Exception as e:
        _fail_streak += 1
        if _fail_streak >= FAIL_LIMIT:
            _disabled = True
            print(f"    ! LLM 连续失败 {_fail_streak} 次，本轮停用会议简介"
                  f"（最后错误: {e}）")
        else:
            print(f"    ! 会议论文简介失败: {e}")
        return None


def event_paper_meta(title: str, authors: str, abstract: str,
                     tag_vocab: list) -> dict | None:
    """有摘要的会议汇报论文：中文标题/简介/标签（键与 event_papers 列对齐）。"""
    return _event_meta(EVENT_PAPER_PROMPT.format(
        title=title, authors=authors, abstract=abstract[:3000],
        tags="、".join(tag_vocab)), tag_vocab)


def event_pdf_meta(title: str, authors: str, text: str,
                   tag_vocab: list) -> dict | None:
    """无摘要的会议汇报论文：用 PDF 抽出的文本概括。"""
    return _event_meta(EVENT_PDF_PROMPT.format(
        title=title, authors=authors, text=text, tags="、".join(tag_vocab)),
        tag_vocab)


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
    # 模型带 thinking 块，思考本身消耗输出额度，上限太低会截断正文甚至空响应
    max_tokens = 3000
    if row["source"] == "tweet":
        prompt = TWEET_PROMPT.format(
            authors=row["authors"], text=row["abstract"][:2500], tags=tags)
    else:
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
        out["abstract_zh"] = (out.get("abstract_zh") or "").strip()
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
