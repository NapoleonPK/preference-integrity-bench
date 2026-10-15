#!/bin/bash
# Run models of a capped free tier until every one is complete: each pass resumes every incomplete model once,
# then waits. For OpenRouter (1,000 requests/day per account, reset 00:00 UTC) and OpenCode (free models stall
# after a few hundred samples a day), unlike run_all.sh which gives up after 3 attempts.
#   bash experiment/run_capped.sh <wait-seconds> <workers> id1 id2 ...
cd "$(dirname "$0")/.." || exit 1
WAIT=$1; W=$2; shift 2
for pass in $(seq 1 30); do
  left=0
  for id in "$@"; do
    python3 experiment/run.py --list | grep -E "^$id +" | grep -q " 930 samples" && continue
    left=1
    echo "=== $id (pass $pass) $(date)"
    python3 experiment/run.py "$id" --workers $W 2>&1 | tee -a "experiment/logs/$id.log" | tail -1
  done
  [ $left = 0 ] && break
  sleep "$WAIT"
done
echo "=== run_capped $* finished $(date)"
