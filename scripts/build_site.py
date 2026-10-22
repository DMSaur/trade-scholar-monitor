#!/usr/bin/env python3
"""生成可视化网页：docs/index.html（内联数据）+ docs/data/latest.json。"""
import json
import re
from collections import Counter
from datetime import datetime

import db

WINDOW_DAYS = 180

SOURCE_LABEL = {"top5": "Top-5 期刊", "nber": "NBER", "scholar": "学者论文", "tweet": "推文"}
JOURNAL_SHORT = {"AER", "QJE", "JPE", "ECMA", "REStud"}

# 这些 venue 视为工作论文/预印本版本，同题去重时让位于期刊版
_WP_VENUES = ("nber", "ssrn", "cesifo", "arxiv", "preprint", "working paper",
              "institute", "university", "报告", "预印本", " reprint")


def _title_key(title: str) -> str:
    """标题归一化：去符号空格、小写、取前 40 字符，用于跨版本去重。"""
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (title or "").lower())
    return t[:40]


def _dedupe_papers(items: list) -> list:
    """论文按归一标题去重：期刊版优先于工作论文版，其次保留日期较新者。"""
    groups: dict = {}
    order: list = []
    for it in items:
        if it["source"] == "tweet" or not it["title"]:
            order.append(("solo", it))
            continue
        k = _title_key(it["title"])
        if not k:
            order.append(("solo", it))
            continue
        if k not in groups:
            groups[k] = []
            order.append(("group", k))
        groups[k].append(it)
    out = []
    for kind, x in order:
        if kind == "solo":
            out.append(x)
            continue
        g = groups[x]
        def rank(it):
            venue = (it.get("venue") or "").lower()
            is_wp = any(w in venue for w in _WP_VENUES)
            return (is_wp, it.get("date") or "", len(it.get("abstract") or ""))
        g.sort(key=rank, reverse=True)
        best = g[0]
        # 被并掉的版本信息并入备注，标注另有工作论文版
        if len(g) > 1:
            others = {it["source"] for it in g[1:]}
            best.setdefault("extra", {})["versions"] = sorted(others)
        out.append(best)
    return out


def collect(conn, scholar_list) -> dict:
    rows = db.items_since(conn, WINDOW_DAYS)
    name_by_scholar = {}
    for s in scholar_list:
        if s.get("openalex_id"):
            name_by_scholar[f"oa:{s['openalex_id']}"] = s["name"]
        if s.get("s2_id"):
            name_by_scholar[f"s2:{s['s2_id']}"] = s["name"]
        if s.get("twitter"):
            name_by_scholar[f"x:{s['twitter'].lstrip('@')}"] = s["name"]
    items = []
    scholars = {}
    for r in rows:
        extra = json.loads(r["extra"] or "{}")
        if r["scholar_id"] and r["scholar_id"] in name_by_scholar:
            extra["scholar_name"] = extra.get("scholar_name") or name_by_scholar[r["scholar_id"]]
        if r["source"] == "scholar" and r["scholar_id"]:
            scholars[r["scholar_id"]] = True
        items.append({
            "uid": r["uid"],
            "source": r["source"],
            "title": r["title"] or "",
            "authors": r["authors"] or "",
            "venue": r["venue"] or "",
            "url": r["url"] or "",
            "date": r["date"] or "",
            # 论文只带中文摘要控制体积；推文带全文
            "abstract": (r["abstract"] or "") if r["source"] == "tweet" else "",
            "summary_zh": r["summary_zh"] or "",
            "title_zh": (r["title_zh"] if "title_zh" in r.keys() else "") or "",
            "tags": json.loads(r["tags"] or "[]"),
            "extra": extra,
        })
    items.sort(key=lambda x: (x["date"], x["uid"]), reverse=True)
    items = _dedupe_papers(items)
    # 学者名单（启用中的），附带近半年动态数
    cnt = Counter(it["extra"].get("scholar_name")
                  for it in items if it.get("extra"))
    scholars_out = []
    for s in scholar_list:
        if not s.get("enabled", True):
            continue
        scholars_out.append({
            "name": s["name"],
            "affiliation": s.get("affiliation") or "",
            "twitter": (s.get("twitter") or "").lstrip("@"),
            "homepage": s.get("homepage") or "",
            "openalex": s.get("openalex_id") or "",
            "s2": s.get("s2_id") or "",
            "items": cnt.get(s["name"], 0),
        })
    return {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "window_days": WINDOW_DAYS, "items": items,
            "scholars": scholars_out}


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>贸易学者动向 · 每日监控</title>
<style>
:root{
  --bg:#f6f5f1; --card:#ffffff; --border:#e5e2d8; --ink:#1c1b17;
  --sub:#6b675c; --accent:#0e5f5b; --accent-soft:#e3efee;
  --top5:#8a2b23; --nber:#1e3a5f; --scholar:#0e5f5b; --tweet:#4a4a48;
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB",
    "Microsoft YaHei","Segoe UI",sans-serif;
  background:var(--bg); color:var(--ink); line-height:1.65; font-size:15px;
}
.wrap{max-width:860px;margin:0 auto;padding:0 18px 60px}
header{padding:34px 0 8px}
h1{font-size:25px;font-weight:700;letter-spacing:.5px}
.subtitle{color:var(--sub);font-size:13.5px;margin-top:4px}
.meta-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.chip{
  display:inline-flex;align-items:center;gap:6px;font-size:12.5px;
  background:var(--card);border:1px solid var(--border);border-radius:20px;
  padding:3px 12px;color:var(--sub);
}
.chip b{color:var(--ink);font-size:13.5px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot.top5{background:var(--top5)}.dot.nber{background:var(--nber)}
.dot.scholar{background:var(--scholar)}.dot.tweet{background:var(--tweet)}
.toolbar{
  position:sticky;top:0;z-index:10;background:var(--bg);
  padding:14px 0 10px;border-bottom:1px solid var(--border);
  display:flex;flex-wrap:wrap;gap:10px;align-items:center;
}
.tabs{display:flex;flex-wrap:wrap;gap:6px}
.tab{
  border:1px solid var(--border);background:var(--card);color:var(--sub);
  border-radius:8px;padding:5px 12px;font-size:13.5px;cursor:pointer;
}
.tab[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
.tab .n{font-size:11.5px;opacity:.75;margin-left:3px}
.seg{display:flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.seg button{
  border:0;background:var(--card);color:var(--sub);padding:5px 12px;
  font-size:13px;cursor:pointer;
}
.seg button[aria-pressed="true"]{background:var(--accent-soft);color:var(--accent);font-weight:600}
#search{
  flex:1;min-width:160px;border:1px solid var(--border);border-radius:8px;
  padding:6px 12px;font-size:13.5px;background:var(--card);color:var(--ink);
  outline:none;
}
#search:focus{border-color:var(--accent)}
#scholarFilter{
  border:1px solid var(--border);border-radius:8px;padding:6px 8px;
  font-size:13px;background:var(--card);color:var(--ink);max-width:170px;
}
.datehead{
  margin:26px 0 10px;font-size:13px;font-weight:700;color:var(--sub);
  letter-spacing:1px;
}
.card{
  background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;margin-bottom:10px;
}
.card:hover{border-color:#cfcaba}
.card-top{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:6px}
.badge{
  font-size:11px;font-weight:700;color:#fff;border-radius:5px;
  padding:1.5px 7px;letter-spacing:.3px;
}
.badge.top5{background:var(--top5)}.badge.nber{background:var(--nber)}
.badge.scholar{background:var(--scholar)}.badge.tweet{background:var(--tweet)}
.venue{font-size:12px;color:var(--sub)}
.card h2{font-size:15.5px;font-weight:600;line-height:1.5;margin:2px 0;
  overflow-wrap:anywhere}
.card h2 a{color:var(--ink);text-decoration:none}
.card h2 a:hover{color:var(--accent);text-decoration:underline}
.authors{font-size:12.5px;color:var(--sub);margin-bottom:6px}
.title-en{font-size:12.5px;color:var(--sub);margin:-2px 0 4px;line-height:1.45;
  overflow-wrap:anywhere}
.title-en a{color:var(--sub);text-decoration:none}
.title-en a:hover{color:var(--accent)}
.summary-zh{
  font-size:13.8px;color:#333;border-left:3px solid var(--accent-soft);
  padding-left:10px;margin:6px 0;overflow-wrap:anywhere;
}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tag{
  font-size:11.5px;color:var(--accent);background:var(--accent-soft);
  border-radius:4px;padding:1px 8px;cursor:pointer;
}
.sub-info{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;font-size:12px;color:var(--sub)}
.tweet-text{font-size:14px;white-space:pre-wrap;margin:6px 0;
  word-break:break-word;overflow-wrap:anywhere}
.rt-mark{font-size:11.5px;color:var(--sub);border:1px solid var(--border);border-radius:4px;padding:0 6px}
.empty{color:var(--sub);text-align:center;padding:60px 0;font-size:14px}
footer{margin-top:44px;color:var(--sub);font-size:12.5px;border-top:1px solid var(--border);padding-top:14px}
footer a{color:var(--sub)}
.roster-note{font-size:13px;color:var(--sub);margin:14px 0 10px}
.roster-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(225px,1fr));gap:10px}
.scard{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.scard-name{font-weight:700;font-size:14.5px;line-height:1.4}
.scard-aff{color:var(--sub);font-size:12.5px;margin:2px 0 4px}
.scard-meta{font-size:11.5px;color:var(--sub);margin-bottom:7px}
.scard-links{display:flex;flex-wrap:wrap;gap:6px}
.slink{font-size:12px;color:var(--accent);text-decoration:none;border:1px solid var(--border);border-radius:5px;padding:1px 7px}
.slink:hover{border-color:var(--accent)}
.suggest{margin-top:26px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
.suggest h3{font-size:15.5px;margin-bottom:4px}
.sg-hint{font-size:12.5px;color:var(--sub);margin-bottom:10px}
.sform{display:grid;gap:8px}
.sform input,.sform textarea{
  border:1px solid var(--border);border-radius:8px;padding:8px 10px;
  font:inherit;font-size:13.5px;width:100%;background:var(--bg);color:var(--ink);
}
.sform input:focus,.sform textarea:focus{outline:none;border-color:var(--accent)}
.sg-btns{display:flex;gap:8px}
.sbtn{
  border:0;background:var(--accent);color:#fff;border-radius:8px;
  padding:7px 16px;font:inherit;font-size:13.5px;cursor:pointer;
}
.sbtn-ghost{background:var(--card);color:var(--accent);border:1px solid var(--accent)}
.sg-ok{font-size:12.5px;color:var(--accent)}
@media (max-width:640px){
  h1{font-size:21px}
  .toolbar{position:static}
  #scholarFilter{max-width:none;flex:1}
}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>贸易学者动向</h1>
  <p class="subtitle">Top-5 期刊贸易论文 · NBER 工作论文 · 贸易学者最新研究 · 学者推文，每日更新</p>
  <div class="meta-row" id="metaRow"></div>
</header>
<div class="toolbar">
  <div class="tabs" id="tabs" role="tablist" aria-label="板块筛选"></div>
  <div class="seg" id="rangeSeg" aria-label="时间范围">
    <button data-range="7" aria-pressed="false">近 7 天</button>
    <button data-range="30" aria-pressed="true">近 30 天</button>
    <button data-range="180" aria-pressed="false">半年</button>
  </div>
  <input id="search" type="search" placeholder="搜索标题、作者、摘要…" aria-label="搜索">
  <select id="scholarFilter" aria-label="按学者筛选"><option value="">全部学者</option></select>
</div>
<main id="list"></main>
<footer>
  <p id="footMeta"></p>
  <p>数据来源：<a href="https://openalex.org" target="_blank" rel="noopener">OpenAlex</a> ·
     <a href="https://www.nber.org" target="_blank" rel="noopener">NBER</a> ·
     <a href="https://x.com" target="_blank" rel="noopener">X（Twitter）</a></p>
</footer>
</div>
<script id="page-data" type="application/json">__DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('page-data').textContent);
const SOURCES = [
  {key:'all',    label:'全部'},
  {key:'top5',   label:'Top-5 期刊'},
  {key:'nber',   label:'NBER'},
  {key:'scholar',label:'学者论文'},
  {key:'tweet',  label:'推文'},
  {key:'roster', label:'学者名单'},
];
const RECIPIENT = '21300680261@m.fudan.edu.cn';
const state = {tab:'all', range:30, q:'', scholar:''};

const WEEK = ['日','一','二','三','四','五','六'];
function fmtDate(d){
  if(!d) return '日期未知';
  const dt = new Date(d + 'T00:00:00');
  if(isNaN(dt)) return d;
  return `${dt.getMonth()+1}月${dt.getDate()}日 星期${WEEK[dt.getDay()]}`;
}
function daysAgo(dateStr){
  const dt = new Date(dateStr + 'T00:00:00');
  return Math.floor((Date.now() - dt.getTime()) / 86400000);
}

/* 顶部统计与学者下拉（计数随筛选联动，在 render 里更新） */
(function init(){
  const meta = document.getElementById('metaRow');
  meta.innerHTML = `
    <span class="chip">数据截至 <b>${DATA.generated_at}</b></span>
    <span class="chip"><span class="dot top5"></span>Top-5 <b id="c-top5">0</b></span>
    <span class="chip"><span class="dot nber"></span>NBER <b id="c-nber">0</b></span>
    <span class="chip"><span class="dot scholar"></span>学者论文 <b id="c-scholar">0</b></span>
    <span class="chip"><span class="dot tweet"></span>推文 <b id="c-tweet">0</b></span>`;

  const names = new Map();
  DATA.items.forEach(it => {
    const n = it.extra && it.extra.scholar_name;
    if(n) names.set(n, (names.get(n)||0)+1);
  });
  const sel = document.getElementById('scholarFilter');
  [...names.keys()].sort((a,b)=>a.localeCompare(b,'zh')).forEach(n => {
    const opt = document.createElement('option');
    opt.value = n; opt.textContent = `${n} (${names.get(n)})`;
    sel.appendChild(opt);
  });
})();

/* 板块 tab（计数随筛选联动） */
(function initTabs(){
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = SOURCES.map(s => `
    <button class="tab" role="tab" data-tab="${s.key}"
      aria-pressed="${s.key===state.tab}">
      ${s.label}<span class="n"></span></button>`).join('');
  tabs.addEventListener('click', e => {
    const btn = e.target.closest('.tab');
    if(!btn) return;
    state.tab = btn.dataset.tab;
    tabs.querySelectorAll('.tab').forEach(b =>
      b.setAttribute('aria-pressed', b===btn ? 'true' : 'false'));
    render();
  });
})();

document.getElementById('rangeSeg').addEventListener('click', e => {
  const btn = e.target.closest('button');
  if(!btn) return;
  state.range = +btn.dataset.range;
  document.querySelectorAll('#rangeSeg button').forEach(b =>
    b.setAttribute('aria-pressed', b===btn ? 'true' : 'false'));
  render();
});
document.getElementById('search').addEventListener('input', e => {
  state.q = e.target.value.trim().toLowerCase(); render();
});
document.getElementById('scholarFilter').addEventListener('change', e => {
  state.scholar = e.target.value; render();
});

function matchBase(it){
  /* 时间范围 + 搜索 + 学者筛选（不含板块） */
  const d = daysAgo(it.date);
  if(isNaN(d) || d > state.range || d < 0) return false;
  if(state.scholar && (!it.extra || it.extra.scholar_name !== state.scholar)) return false;
  if(state.q){
    const e = it.extra || {};
    const hay = [it.title, it.authors, it.venue, it.summary_zh,
                 it.abstract || '', (it.tags||[]).join(' '),
                 e.scholar_name || '', e.handle || '', e.nber_id || '',
                 e.journal_short || ''].join(' ').toLowerCase();
    if(!hay.includes(state.q)) return false;
  }
  return true;
}

function cardHTML(it){
  const e = it.extra || {};
  let badges = '';
  let venueInfo = '';
  if(it.source === 'top5'){
    const js = e.journal_short || '';
    badges = `<span class="badge top5">${js}</span>`;
    venueInfo = `<span class="venue">${it.venue||''}</span>`;
  }else if(it.source === 'nber'){
    badges = `<span class="badge nber">NBER</span>`;
    venueInfo = `<span class="venue">NBER Working Paper ${e.nber_id||''}</span>`;
  }else if(it.source === 'scholar'){
    const who = e.scholar_name || '';
    badges = `<span class="badge scholar">学者论文</span>` +
      (who ? `<span class="venue">${who}</span>` : '');
    venueInfo = `<span class="venue">${it.venue||e.work_type||''}</span>`;
  }else{
    const rt = e.is_retweet ? ' <span class="rt-mark">转发</span>' : '';
    badges = `<span class="badge tweet">@${e.handle||''}</span>${rt}`;
    venueInfo = `<span class="venue">${e.name||''}</span>`;
  }
  const stats = it.source === 'tweet'
    ? `<div class="sub-info"><span>赞 ${e.likes||0}</span><span>转 ${e.retweets||0}</span><span>浏览 ${e.views||0}</span></div>`
    : '';
  const text = it.source === 'tweet'
    ? `<p class="tweet-text">${esc(it.abstract||'')}</p>` : '';
  // 推文正文已经完整展示；论文标题有中文翻译时中文为主、原文为副
  const showTitle = !(it.source === 'tweet' && it.abstract);
  const zh = it.title_zh || '';
  const mainTitle = showTitle ? (zh || it.title || it.summary_zh || '(无标题)') : '';
  const titleHTML = !mainTitle ? '' : (it.url
    ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(mainTitle)}</a>`
    : esc(mainTitle));
  const titleEn = (showTitle && zh && it.title && zh !== it.title)
    ? `<p class="title-en">${it.url
        ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>`
        : esc(it.title)}</p>` : '';
  const summary = it.summary_zh && it.summary_zh !== '（非贸易领域）'
    ? `<p class="summary-zh">${esc(it.summary_zh)}</p>` : '';
  const authors = it.authors && it.source !== 'tweet'
    ? `<p class="authors">${esc(it.authors)}</p>` : '';
  const tags = (it.tags||[]).length
    ? `<div class="tags">${it.tags.map(t =>
        `<span class="tag" data-tag="${esc(t)}">${esc(t)}</span>`).join('')}</div>` : '';
  return `<article class="card">
    <div class="card-top">${badges}${venueInfo}</div>
    ${titleHTML ? `<h2>${titleHTML}</h2>` : ''}
    ${titleEn}
    ${authors}${text}${summary}${stats}${tags}
  </article>`;
}

function esc(s){
  return String(s==null?'':s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function rangeLabel(r){
  return r === 180 ? '近半年' : (r === 7 ? '近 7 天' : '近 30 天');
}

function groupLabel(dateStr){
  /* 半年视图按月分组，其余按日分组 */
  if(!dateStr) return '日期未知';
  if(state.range > 60){
    const dt = new Date(dateStr + 'T00:00:00');
    return `${dt.getFullYear()}年${dt.getMonth()+1}月`;
  }
  return fmtDate(dateStr);
}

function rosterHTML(){
  const cards = DATA.scholars.map(s => {
    const links = [];
    if(s.homepage) links.push(`<a class="slink" href="${esc(s.homepage)}" target="_blank" rel="noopener">主页</a>`);
    if(s.twitter) links.push(`<a class="slink" href="https://x.com/${esc(s.twitter)}" target="_blank" rel="noopener">@${esc(s.twitter)}</a>`);
    if(s.openalex) links.push(`<a class="slink" href="https://openalex.org/${esc(s.openalex)}" target="_blank" rel="noopener">OpenAlex</a>`);
    if(s.s2) links.push(`<a class="slink" href="https://www.semanticscholar.org/author/${esc(s.s2)}" target="_blank" rel="noopener">S2</a>`);
    return `<div class="scard">
      <div class="scard-name">${esc(s.name)}</div>
      <div class="scard-aff">${esc(s.affiliation)}</div>
      <div class="scard-meta">近半年 ${s.items} 条动态</div>
      <div class="scard-links">${links.join('')}</div>
    </div>`;
  }).join('');
  return `<p class="roster-note">共收录 ${DATA.scholars.length} 位学者，「动态」为近半年条目数。</p>
    <div class="roster-grid">${cards}</div>
    <div class="suggest">
      <h3>建议新增学者</h3>
      <p class="sg-hint">填写后点「打开邮件」发到维护者邮箱，或点「复制内容」粘贴到任意渠道。</p>
      <div class="sform">
        <input id="sg-name" placeholder="学者姓名（必填）">
        <input id="sg-org" placeholder="所在机构">
        <input id="sg-tw" placeholder="X 账号（如 @ChadBown）">
        <input id="sg-hp" placeholder="个人主页">
        <textarea id="sg-why" rows="2" placeholder="推荐理由（可选）"></textarea>
        <div class="sg-btns">
          <button class="sbtn" id="sg-send">打开邮件</button>
          <button class="sbtn sbtn-ghost" id="sg-copy">复制内容</button>
        </div>
        <p class="sg-ok" id="sg-ok" hidden>已复制到剪贴板。</p>
      </div>
    </div>`;
}

function suggestText(){
  const v = id => (document.getElementById(id).value || '').trim();
  const line = (label, val) => val ? `${label}：${val}\n` : '';
  return line('学者姓名', v('sg-name')) + line('所在机构', v('sg-org')) +
    line('X 账号', v('sg-tw')) + line('个人主页', v('sg-hp')) +
    line('推荐理由', v('sg-why')) + '\n来自「贸易学者动向」页面的建议';
}

function bindRoster(root){
  root.addEventListener('click', e => {
    if(e.target.id === 'sg-send'){
      const name = (document.getElementById('sg-name').value || '').trim();
      const subject = `建议新增贸易学者：${name || '（未填姓名）'}`;
      window.location.href =
        `mailto:${RECIPIENT}?subject=${encodeURIComponent(subject)}` +
        `&body=${encodeURIComponent(suggestText())}`;
    }else if(e.target.id === 'sg-copy'){
      const done = () => {
        const ok = document.getElementById('sg-ok');
        ok.hidden = false;
        setTimeout(() => { ok.hidden = true; }, 2500);
      };
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(suggestText()).then(done).catch(() => {});
      }else{
        const ta = document.createElement('textarea');
        ta.value = suggestText();
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        done();
      }
    }
  });
}

function renderRoster(){
  const list = document.getElementById('list');
  list.innerHTML = rosterHTML();
  bindRoster(list);
}

function render(){
  const list = document.getElementById('list');
  if(state.tab === 'roster'){
    document.getElementById('footMeta').textContent =
      `学者名单共 ${DATA.scholars.length} 人（不含已停用条目）。`;
    renderRoster();
    return;
  }
  const base = DATA.items.filter(matchBase);

  /* 板块 tab 计数与顶部统计随筛选联动 */
  const perSource = {top5:0, nber:0, scholar:0, tweet:0};
  base.forEach(it => perSource[it.source]++);
  document.querySelectorAll('#tabs .tab').forEach(btn => {
    const k = btn.dataset.tab;
    const n = k === 'all' ? base.length
      : (k === 'roster' ? DATA.scholars.length : perSource[k]);
    btn.querySelector('.n').textContent = n;
  });
  ['top5','nber','scholar','tweet'].forEach(k => {
    document.getElementById('c-'+k).textContent = perSource[k];
  });
  document.getElementById('footMeta').textContent =
    `当前筛选 ${rangeLabel(state.range)}，共 ${base.length} 条；数据共覆盖近半年。`;

  const items = state.tab === 'all' ? base
    : base.filter(it => it.source === state.tab);
  if(!items.length){
    list.innerHTML = '<p class="empty">该筛选条件下暂无条目。</p>';
    return;
  }
  let html = '', lastGroup = '';
  items.forEach(it => {
    const g = groupLabel(it.date);
    if(g !== lastGroup){
      lastGroup = g;
      html += `<div class="datehead">${g}</div>`;
    }
    html += cardHTML(it);
  });
  list.innerHTML = html;
}

document.getElementById('list').addEventListener('click', e => {
  const tag = e.target.closest('.tag');
  if(!tag) return;
  const input = document.getElementById('search');
  input.value = tag.dataset.tag;
  state.q = tag.dataset.tag.toLowerCase();
  render();
});

render();
</script>
</body>
</html>
"""


def build(conn, scholar_list):
    data = collect(conn, scholar_list)
    docs = db.ROOT / "docs"
    (docs / "data").mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(docs / "data" / "latest.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    html = TEMPLATE.replace("__DATA_JSON__", data_json)
    with open(docs / "index.html", "w", encoding="utf-8") as f:
        f.write(html)
    n = len(data["items"])
    print(f"    docs/index.html 写入完成（{n} 条，{len(html)//1024} KB）")


if __name__ == "__main__":
    conn = db.connect()
    with open(db.ROOT / "config" / "scholars.yaml", encoding="utf-8") as f:
        import yaml
        scholar_list = yaml.safe_load(f).get("scholars", [])
    build(conn, scholar_list)
