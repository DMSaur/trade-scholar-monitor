# 贸易学者动向每日监控网页

## 目标

在本目录（前沿文献监控）建一个每日自动更新的可视化网页，四个板块：Top-5 期刊最新贸易论文、NBER 工作论文、贸易学者最新论文（学者动态）、学者推文。本机每天上午自动运行并推送到云端，手机电脑都能看。

## 关键技术决策（基于已查明的本机条件）

1. **学者论文源用 OpenAlex 替代 Google Scholar**。Scholar 没有官方 API，爬取容易被封。OpenAlex 免费、无需 key，覆盖所有经济学者的论文（含 working paper 版本），按作者 ID 查最新作品稳定可靠。学者个人主页 URL 会放在网页的学者卡片里可点击；自动监控主页内容作为二期扩展。
2. **推文用本机已有的 xreach CLI**（复用资讯追踪 v2 的 xreach_fetcher.py 模式，走本地代理 127.0.0.1:7897），按 `from:学者handle` 搜最近 7 天推文。
3. **Top-5 期刊用 OpenAlex 按期刊 ISSN 过滤**（AER/QJE/JPE/Econometrica/REStud），先用贸易关键词初筛，再由 LLM 确认相关性，解决 top5 贸易论文稀疏问题。
4. **NBER 用已验证的 RSS**：ITI 项目 feed（你 CLAUDE.md 里已验证）加 NBER 全站新论文 feed，关键词过滤。
5. **中文摘要用 DashScope**（复用你已有的 key），只对新条目生成一句中文摘要加主题标签，按条目 ID 缓存不重复花钱。
6. **发布走 GitHub Pages**：新仓库 DMSaur/trade-scholar-monitor，推送后直接用 GitHub API 开启 Pages（指向 docs/ 目录），网址形如 dmsaur.github.io/trade-scholar-monitor，与你 ai-trade-us-china 同款，全程不需要你操作。如果你想用 Cloudflare Pages（资讯追踪同款），需要你在 CF 后台手动连一次新仓库，二选一即可。

## 项目结构

```
前沿文献监控/
├── CLAUDE.md                # 项目说明：架构、如何加学者、如何手动跑
├── config/
│   ├── scholars.yaml        # 学者名单（可编辑）
│   └── topics.yaml          # 贸易关键词表（过滤与打标签共用）
├── scripts/
│   ├── main.py              # 每日入口：抓取 → 去重 → 摘要 → 生成网页
│   ├── db.py                # SQLite 状态库（按条目 ID 去重，保留全部历史）
│   ├── core/summarize.py    # LLM 中文摘要与主题标签
│   ├── fetchers/
│   │   ├── top5.py          # OpenAlex 按期刊拉取
│   │   ├── nber.py          # NBER RSS
│   │   ├── scholars.py      # OpenAlex 按学者拉最新作品
│   │   └── tweets.py        # xreach 抓学者推文
│   └── build_site.py        # 生成 docs/index.html + docs/data/*.json
├── data/monitor.db          # SQLite（gitignore）
├── docs/                    # 发布目录（index.html + data JSON）
├── run_daily.sh             # launchd 调用的包装：环境变量、跑批、git push
└── com.dimo.trademonitor.plist
```

## 学者名单（约 30 人，我拟默认）

YAML 每人一条：姓名、单位、OpenAlex ID、Twitter handle、个人主页 URL。名单初稿：Autor、Dorn、Acemoglu、Melitz、Feenstra、Hummels、Hanson、Goldberg、Pavcnik、Schott、Khandelwal、Handley、Amiti、Itskhoki、Fajgelbaum、Caliendo、Parro、Antràs、Costinot、Donaldson、Eaton、Kortum、Arkolakis、Allen、Redding、Grossman、Helpman、Rodrik、Krugman、Bown、Irwin、Weinstein、Bernard、Rossi-Hansberg。实施时逐人调 OpenAlex 搜索 API 核对身份后写入 ID；有 Twitter 的配 handle（如 Bown、Irwin、Setser 活跃度高）。YAML 里预留一个默认关闭的中国学者区块（刘志阔、马弘、鞠建东、余淼杰等），你改一行即可启用。

## 网页设计

单文件静态页，中文界面，无构建依赖。顶部显示最近更新时间和各源当日新增计数；四个 tab（期刊、NBER、学者动态、推文）；每条显示标题（可点原文链接）、作者、期刊或编号、日期、一句中文摘要、主题标签；支持日期范围筛选（今天/7 天/30 天）、关键词搜索、按学者筛选。数据存 docs/data/latest.json（最近 30 天），历史按日归档 JSON 可回看。

## 定时与发布

- run_daily.sh：设好 Python（pyenv 3.11）和代理环境变量，跑 main.py，成功后 git commit 并 push docs/。
- launchd plist com.dimo.trademonitor.plist，每天上午 9:30 运行（与你的 journal_monitor 9:00 错开），日志写 logs/。
- 首次运行时建 GitHub 仓库、推送、用 API 开启 Pages。

## 实施步骤

1. 建目录结构、config、学者名单（逐人核对 OpenAlex ID 和 Twitter handle）。
2. 写 fetchers（top5、nber、scholars、tweets）和 SQLite 去重层；先验证 xreach 在本机可用，不可用则推文板块降级并提示。
3. 接入 DashScope 中文摘要，加缓存。
4. build_site.py 生成网页（会参考你 Vault 里资讯追踪 v2 的页面和 viz-page 技能的做法）。
5. 手动跑一次 `main.py --days 60` 灌入历史数据，浏览器检查四个板块和筛选功能。
6. 建 GitHub 仓库推送、开 Pages、装 launchd 定时任务，手动 kickstart 验证一轮完整流程。

## 你需要做的

方案选 GitHub Pages 路线则全程无需操作；若日后想换成 Cloudflare Pages，在 CF 后台连一次仓库即可。API key 复用已有的，不新增任何账号。