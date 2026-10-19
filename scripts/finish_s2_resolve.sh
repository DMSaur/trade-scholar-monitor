#!/bin/zsh
# 等 S2 限流窗口，磨完全部 34 人主档案解析，然后提交配置并触发一次
# 30 天补灌。完成后可删除本文件。
VAULT="/Users/dimo/Documents/Obsidian Vault/03-Research/前沿文献监控"
RUNTIME="$HOME/.trade-monitor"
PY="$HOME/.pyenv/versions/3.11.0/bin/python3"

for i in {1..40}; do
  n=$("$PY" -c "import json;print(len(json.load(open('/tmp/s2_main_report.json'))))" 2>/dev/null || echo 0)
  echo "---- 第 $i 轮 已解析 $n/34 $(date '+%F %T') ----"
  if [ "$n" -ge 34 ]; then break; fi
  "$PY" "$VAULT/scripts/resolve_s2_main.py" 2>&1 | /usr/bin/grep -v "^.. "
  sleep 900
done

cd "$VAULT" || exit 1
git add config/scholars.yaml scripts/resolve_s2_main.py 2>/dev/null
if ! git diff --cached --quiet; then
  git -c user.name=Dimo -c user.email=21300680261@m.fudan.edu.cn \
    commit -m "学者 S2 主档案 ID 解析完成（按 hIndex 取主档案）"
  git push -q origin main
fi

cd "$RUNTIME" || exit 1
git pull --ff-only origin main
./run_daily.sh --days 30
echo "---- s2 主档案收尾完成 $(date '+%F %T') ----"
