#!/usr/bin/env bash
# فقط شمارندهٔ عددی بارگذاری GPU ثبت می‌شود؛ پیام‌ها و متن درخواست وارد لاگ نمی‌شوند.
set -uo pipefail
fifo="$(mktemp -u /tmp/ats-engine-log.XXXXXX)"
mkfifo "${fifo}"
grep --line-buffered -oE 'offloaded [0-9]+/[0-9]+ layers to GPU' \
  < "${fifo}" &
filter_pid=$!
/usr/lib/ollama/llama-server "$@" > "${fifo}" 2>&1 &
engine_pid=$!
stop_engine() { kill -TERM "${engine_pid}" 2>/dev/null || true; }
trap stop_engine TERM INT
wait "${engine_pid}"
result=$?
# wait ممکن است با رسیدن SIGTERM زودتر برگردد؛ فرصت shutdown حفظ می‌شود.
if kill -0 "${engine_pid}" 2>/dev/null; then
  wait "${engine_pid}" || true
fi
wait "${filter_pid}" || true
rm -f -- "${fifo}"
exit "${result}"
