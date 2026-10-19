#!/bin/bash
# 每日更新入口：跑抓取脚本，成功后提交并推送 docs/ 到 GitHub Pages
# launchd 调用；也可手动执行 ./run_daily.sh [--days N]

set -e
cd "$(dirname "$0")"

PYENV_PY="$HOME/.pyenv/versions/3.11.0/bin/python3"
export PATH="$HOME/.nvm/versions/node/v24.14.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

mkdir -p logs
LOG="logs/$(date +%Y-%m-%d).log"

echo "---- $(date '+%F %T') 开始 ----" >> "$LOG"
# 拉取仓库最新配置（学者名单在 Vault 侧编辑后推送，这里同步）
git pull --ff-only origin main >> "$LOG" 2>&1 || echo "git pull 失败，用本地版本继续" >> "$LOG"
"$PYENV_PY" scripts/main.py "$@" >> "$LOG" 2>&1 || {
  echo "main.py 失败，详见 $LOG" >&2
  exit 1
}
echo "---- $(date '+%F %T') 完成，推送 docs/ ----" >> "$LOG"

git add docs/ >/dev/null
# index.html 与 latest.json 在 .gitignore 里（Vault 侧不提交生成物），
# 运行时是唯一发布方，用 -f 强制加入
git add -f docs/index.html docs/data/latest.json >/dev/null 2>&1
if git diff --cached --quiet; then
  echo "无新改动，跳过推送" >> "$LOG"
else
  git -c user.name=dimo -c user.email=dimo@local \
    commit -m "每日更新 $(date +%F)" >/dev/null
  git push origin main >> "$LOG" 2>&1
fi
echo "---- $(date '+%F %T') 发布结束 ----" >> "$LOG"
