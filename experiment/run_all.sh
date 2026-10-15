#!/bin/bash
# Run every model in a tier, one after another; each is retried (resumed) up to 3 times.
#   bash experiment/run_all.sh claude      # Claude models + retest  (your Claude subscription)
#   bash experiment/run_all.sh openai      # GPT-6 models via Pi + Codex control (ChatGPT subscription; `pi` /login first)
#   bash experiment/run_all.sh nvidia      # NVIDIA build free models (~40 requests/min)
#   bash experiment/run_all.sh openrouter  # OpenRouter free models (1,000 requests/day: ~1.4 days per model)
#   bash experiment/run_all.sh opencode    # OpenCode free models + harness control
# Leave it running (e.g. `nohup bash experiment/run_all.sh openrouter > experiment/logs/openrouter.log 2>&1 &`).
cd "$(dirname "$0")/.." || exit 1
case "$1" in
  claude)     IDS="claude-haiku-5-5 claude-sonnet-5-5 claude-opus-5-5 claude-haiku-5-5@retest"; W=2 ;;   # Opus paused then resumed, see PROTOCOL §12
  openai)     IDS="gpt-6-luna gpt-6-astra gpt-6.1-sol gpt-6-luna@codex"; W=4 ;;
  nvidia)     IDS="nemotron-3-ultra nemotron-3-super glm-5.3 muse-glimmer-30b kimi-k3 deepseek-v4.1-flash gpt-oss-20b"; W=4 ;;
  openrouter) IDS="inkling dots-3-note-preview laguna-s-2.1 gemma-4-31b"; W=3 ;;
  opencode)   IDS="step-5-preview nemotron-3-ultra@opencode mimo-v2.6-flash"; W=3 ;;   # MiMo last: its free endpoint stalled 2026-10-09
  *) echo "usage: $0 claude|openai|nvidia|openrouter|opencode"; exit 1 ;;
esac
mkdir -p experiment/logs
for id in $IDS; do
  for attempt in 1 2 3; do
    echo "=== $id (attempt $attempt) $(date)"
    if python3 experiment/run.py "$id" --workers $W 2>&1 | tee -a "experiment/logs/$id.log" | grep -q "^COMPLETE"; then break; fi
    sleep 600
  done
done
echo "=== tier $1 finished $(date)"
