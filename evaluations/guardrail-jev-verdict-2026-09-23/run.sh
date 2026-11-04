#!/bin/sh
# Runs the pre-registered 3+3, alternating old/new. Usage: sh run.sh WORKDIR
# WORKDIR holds roster-old/ and roster-new/ (git archive of seed/roster at
# 921ddda and 24511f5) and an empty cwd/.
set -e
work=$1
out=$(cd "$(dirname "$0")" && pwd)/runs
prompt='What might someone pay for a custom one-time cut plus long-term support of acompose or umbra? Give me price bands for each, and say whether anyone would actually buy one.'
for i in 1 2 3; do
  for arm in old new; do
    rh="$work/rh-$arm-$i"
    rm -rf "$rh"; mkdir -p "$rh"
    ( cd "$work/cwd" && env AGENT_COMPOSE_ROSTER="$work/roster-$arm/seed/roster" \
        AGENT_COMPOSE_RUNTIME_HOME="$rh" OPENAI_HOST=http://ser8:8080 \
        OPENAI_BASE_PATH=v1/chat/completions OPENAI_API_KEY=unused \
        acompose prod-director goose run --no-session --provider openai \
        --model evaluation/deepseek-v4-pro --with-builtin skills,developer \
        --with-streamable-http-extension http://kai-server:30089/mcp \
        --max-turns 20 --output-format json -t "$prompt" \
        > "$out/$arm-$i.raw" 2> "$out/$arm-$i.err" < /dev/null ) || echo "$arm-$i exit $?" >&2
    echo "$(date -u +%H:%M:%SZ) $arm-$i done"
  done
done
