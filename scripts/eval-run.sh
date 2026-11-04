#!/bin/sh
# Run the board through Inspect against Agent Proxy. Unscored on purpose: the
# scorer is a human, and Inspect calls the repetition an epoch.
set -e
# Inspect loads a task file with the working directory set to that file's
# folder, so a relative path here resolves under evalkit/ and vanishes.
absolute() {
  case $1 in
  /*) printf '%s\n' "$1" ;;
  *) printf '%s\n' "$PWD/$1" ;;
  esac
}

challenges=$(absolute "${EVAL_CHALLENGES:-challenges.yaml}")
prompts=$(absolute "${EVAL_PROMPTS:-.evalkit/prompts}")
logs=$(absolute "${EVAL_LOGS:-.evalkit/logs}")
epochs=${EVAL_EPOCHS:-5}

AGENTPROXY_BASE_URL=${AGENT_PROXY_BASE:-http://ser8:8080/v1}
AGENTPROXY_API_KEY=${AGENTPROXY_API_KEY:-unused}
export AGENTPROXY_BASE_URL AGENTPROXY_API_KEY

model=${AGENT_PROXY_MODEL:-evaluation/deepseek-v4-pro}
uv run --all-extras inspect eval evalkit/task.py \
  --model "openai-api/agentproxy/$model" \
  --epochs "$epochs" \
  --no-score \
  --log-dir "$logs" \
  -T challenges="$challenges" \
  -T prompts="$prompts" \
  "$@"
