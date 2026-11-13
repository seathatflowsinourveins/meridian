#!/bin/bash
# Runs INSIDE `unshare -rn` (own network namespace: only its own loopback, no route out).
# args: ARM(without|with) TAG RUNDIR
set -u
EV=$HOME/src/meridian-ab/0009; S=$EV/scripts; H=$EV/dsh-home; PORT=18909
arm=$1 tag=$2 d=$3
ip link set lo up || { echo "lo-up-failed" > "$EV/$tag.exit"; exit 6; }
python3 -I "$S/capture_server.py" "$PORT" "$EV/capture/$tag" & srv=$!
for i in $(seq 100); do ss -Hltn "sport = :$PORT" | grep -q . && break; sleep 0.05; done
extra=(); [ "$arm" = with ] && extra=(--patch "$EV/with/with-only.cordis.yml")
cd "$d" && test ! -e .env || { kill "$srv"; echo "env-file-present" > "$EV/$tag.exit"; exit 5; }
start=$(date +%s%N)
env -u DSH_PERMISSION_MODE -u DEEPSEEK_API_KEY -u DSH_SYSTEM_PROMPT \
  DSH_HOME="$H" DSH_AGENTS_HOME="$EV/agents-home" DSH_TELEMETRY_DISABLED=1 \
  DEEPSEEK_BASE_URL="http://127.0.0.1:$PORT/anthropic" DEEPSEEK_SEARCH_BASE_URL="http://127.0.0.1:$PORT/anthropic/v1" \
  DEEPSEEK_API_KEY=ab-loopback-placeholder-not-a-key \
  timeout --signal=INT --kill-after=30 300 dsh --profile "ab-$arm" --patch "$EV/ab-overlay.cordis.yml" "${extra[@]}" \
  --json --permission-mode danger-full-access --approval-policy never - < "$EV/probe.txt" > "$EV/$tag.jsonl" 2> "$EV/$tag.stderr"
rc=$?
end=$(date +%s%N)
printf 'exit=%s\nms=%s\n' "$rc" "$(( (end - start) / 1000000 ))" > "$EV/$tag.exit"
kill "$srv" 2>/dev/null; wait "$srv" 2>/dev/null
exit 0
