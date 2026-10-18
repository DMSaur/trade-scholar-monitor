#!/bin/zsh
# 一次性引导脚本：等 API 共享额度恢复 → 查全学者 s2_id → 回填配置 →
# 首次灌入 30 天数据并发布。完成后可删除本文件。
# 用法: zsh scripts/bootstrap.sh （或 nohup 后台跑）

cd "$(dirname "$0")/.."
PY="$HOME/.pyenv/versions/3.11.0/bin/python3"
mkdir -p logs

for i in {1..30}; do
  echo "---- 第 $i 轮 $(date '+%F %T') ----" >> logs/bootstrap.log
  "$PY" scripts/lookup_scholars_s2.py >> logs/bootstrap.log 2>&1
  n=$("$PY" -c "import json;print(len(json.load(open('/tmp/s2_lookup.json'))))" 2>/dev/null || echo 0)
  echo "锚点进度 $n/20" >> logs/bootstrap.log
  if [ "$n" -ge 20 ]; then break; fi
  sleep 1500
done

"$PY" scripts/fill_scholars.py >> logs/bootstrap.log 2>&1
./run_daily.sh --days 30 >> logs/bootstrap.log 2>&1 \
  || echo "run_daily 失败，明天 9:30 的定时任务会自动补上" >> logs/bootstrap.log
echo "---- 引导结束 $(date '+%F %T') ----" >> logs/bootstrap.log
