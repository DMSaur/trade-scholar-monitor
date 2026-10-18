# CLAUDE.md — 贸易学者动向每日监控

每天早上自动抓取四个来源的新内容，生成静态可视化网页并发布到 GitHub Pages。
本文件给未来的 Claude/人看：架构、日常操作、常见问题。

## 页面与数据流

```
每天 9:30 (launchd: com.dimo.trademonitor)
  → run_daily.sh
    → scripts/main.py
       1. Top-5 期刊     OpenAlex 按期刊 ISSN，贸易关键词初筛
       2. NBER 工作论文  OpenAlex NBER 源 (S2809516038)，关键词初筛
       3. 学者最新论文   OpenAlex 按作者 ID（学者名单见 config/scholars.yaml）
       4. 学者推文       xreach CLI 按学者 handle 抓时间线
       5. DashScope 生成一句中文摘要 + 主题标签；Top-5/NBER 同时做
          贸易相关性二筛（关键词命中的候选由模型确认，非贸易的隐藏）
    → docs/index.html（内联数据）+ docs/data/latest.json
    → git commit + push → GitHub Pages 自动发布
```

- 线上地址：https://dmsaur.github.io/trade-scholar-monitor/
- 本地直接打开：`docs/index.html`（数据内联，无需起服务）
- 去重与历史：`data/monitor.db`（SQLite，按 uid 去重，保留全部历史；网页只展示近 30 天）
- 日志：`logs/YYYY-MM-DD.log`

## 手动运行

```bash
./run_daily.sh                  # 正常每日流程（回看7天），含推送
scripts/main.py --days 60       # 只跑抓取+网页，不推送；首次灌数据用
scripts/main.py --no-llm        # 跳过摘要（不花钱）
scripts/main.py --no-tweets     # 跳过推文（代理没开时用）
```

## 配置

- `config/scholars.yaml`：学者名单。每人 `name / affiliation / openalex_id /
  twitter / homepage`。改完下次运行生效。OpenAlex ID 在 https://openalex.org
  搜人名即可查到（URL 里 A 开头的编号）。
- `config/topics.yaml`：贸易关键词（初筛用）和中文标签词表（LLM 打标签用）。
- `.env`（不入库）：`DASHSCOPE_API_KEY` 摘要用；`OPENALEX_API_KEY` 强烈建议配置。

## 依赖与前提

- Python：`~/.pyenv/versions/3.11.0`（yaml / requests / feedparser / openai）
- xreach：npm 全局（抓推文用），需要本地代理 `127.0.0.1:7897` 开着；
  没开代理时推文板块为空，其余板块正常
- launchd：`~/Library/LaunchAgents/com.dimo.trademonitor.plist`
  重装：`launchctl unload` 后 `load` 该文件

## 已知问题与对策

- **OpenAlex 免费额度按 IP 共享（约每天几十次）**，白天容易 429。代码已做
  直连/本地代理双路自动切换 + 退避重试；配置 `OPENALEX_API_KEY` 后独享
  每天 1000 次，问题根治。key 在 https://openalex.org/settings/api-key
  （用复旦邮箱登录）。
- **NBER 官网 RSS 已失效**（2026-10 改版），NBER 源改走 OpenAlex，见上。
- **学者消歧**：OpenAlex 的作者归属偶有错乱（同名学者），发现张冠李戴时
  在 scholars.yaml 里核对该人的 openalex_id。
- **xreach 偶发超时**：脚本单次失败只跳过该学者，下轮自动补上（推文按
  时间窗去重，不会重复入库）。
