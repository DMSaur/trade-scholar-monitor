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
"$PYENV_PY" scripts/main.py "$@" >> "$LOG" 2>&1 || {
  echo "main.py 失败，详见 $LOG" >&2
  exit 1
}
echo "---- $(date '+%F %T') 完成，推送 docs/ ----" >> "$LOG"

git add docs/ >/dev/null
if git diff --cached --quiet; then
  echo "无新改动，跳过推送" >> "$LOG"
else
  git -c user.name=dimo -c user.email=dimo@local \
    commit -m "每日更新 $(date +%F)" >/dev/null
  git push origin main >> "$LOG" 2>&1
fi
echo "---- $(date '+%F %T') 发布结束 ----" >> "$LOG"
