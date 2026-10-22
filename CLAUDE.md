# CLAUDE.md — 贸易学者动向每日监控

每天早上自动抓取四个来源的新内容，生成静态可视化网页并发布到 GitHub Pages。
本文件给未来的 Claude/人看：架构、日常操作、常见问题。

## 双目录结构（重要）

- **本目录（Vault 内）**：配置与代码的工作副本。学者名单、关键词在这里改，
  改完 commit + push 即可，运行时会自动拉取。也可以在这里手动跑脚本调试。
- **`~/.trade-monitor/`**：launchd 实际运行用的克隆。因为 macOS 隐私保护
  不让 launchd 进程访问 Documents 目录（会报 Operation not permitted），
  定时任务放 home 目录下跑，结果照常推 GitHub。它的 monitor.db 是去重与
  摘要的权威状态（随 git 同步）。
- 页面与数据每次运行后推 GitHub Pages：
  **https://dmsaur.github.io/trade-scholar-monitor/**

## 页面与数据流

```
每天 9:30 (launchd: com.dimo.trademonitor)
  → ~/.trade-monitor/run_daily.sh
    → git pull（同步本目录推送的配置）
    → scripts/main.py
       1. Top-5 期刊     OpenAlex 按期刊 ISSN，贸易关键词初筛
       2. NBER 工作论文  OpenAlex NBER 源 (S2809516038)，关键词初筛
       3. 学者最新论文   OpenAlex 按作者 ID（每人一天一次请求，日期可靠）；
                         失败时自动降级 Semantic Scholar 批量接口
       4. 学者推文       xreach CLI 按学者 handle 抓时间线
       5. DeepSeek 生成中文标题翻译、一句摘要和主题标签；Top-5/NBER 同时做
          贸易相关性二筛（关键词命中的候选由模型确认，非贸易的隐藏）
    → docs/index.html（内联数据；论文按归一标题去重，期刊版优先）
    → git commit + push → GitHub Pages 自动发布
```

- 线上地址：https://dmsaur.github.io/trade-scholar-monitor/
- 本地直接打开：`docs/index.html`（数据内联，无需起服务）
- 去重与历史：`data/monitor.db`（SQLite，按 uid 去重，保留全部历史；网页数据覆盖近半年，页面默认显示近 30 天，可切半年视图）
- 日志：`logs/YYYY-MM-DD.log`

## 手动运行

```bash
./run_daily.sh                  # 正常每日流程（回看7天），含推送
scripts/main.py --days 60       # 只跑抓取+网页，不推送；首次灌数据用
scripts/main.py --no-llm        # 跳过摘要（不花钱）
scripts/main.py --no-tweets     # 跳过推文（代理没开时用）
```

## 配置

- `config/scholars.yaml`：学者名单。每人 `name / affiliation / s2_id /
  twitter / homepage`。改完下次运行生效。s2_id 在
  https://semanticscholar.org 搜到本人主页后从 URL 的 authorId 复制。
  批量补录新学者的完整流程（含同名陷阱与两个核验脚本）见
  `scripts/新增学者指南.md`，先读它再动手。
- `config/topics.yaml`：贸易关键词（初筛用）和中文标签词表（LLM 打标签用）。
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
  （用复旦邮箱登录，已有账号）。
- **中文摘要**：DeepSeek（Anthropic 兼容接口），凭据在 `.env` 的
  `ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL` 三项。
  换其他兼容服务商时改这三行即可。代码有熔断，接口不可用时不会拖慢抓取。
- **S2 学者同名分裂档案**：s2_id 一律取 hIndex 最高的主档案
  （scripts/resolve_s2_main.py 的解析结果）。若某学者论文明显偏少，
  重新跑一次该脚本即可。
- **xreach 偶发超时**：脚本单次失败只跳过该学者，下轮自动补上（推文按
  时间窗去重，不会重复入库）。
- **launchd 与 Documents 权限**：定时任务必须在 `~/.trade-monitor` 跑，
  直接指向 Vault 目录会报 Operation not permitted。
