#!/bin/sh
# One live request through Agent Proxy, so a broken transport surfaces before a
# full board run rather than during one. Prints the model list and one answer.
set -e
base=${AGENT_PROXY_BASE:-http://ser8:8080/v1}
model=${AGENT_PROXY_MODEL:-evaluation/deepseek-v4-pro}

echo "proxy: $base"
curl -sf -m 10 "$base/models" \
  | python3 -c "import json,sys; print('models:', ', '.join(sorted(m['id'] for m in json.load(sys.stdin)['data'])))"

echo "asking $model"
curl -sf -m 90 "$base/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"system\",\"content\":\"Answer in under 15 words.\"},{\"role\":\"user\",\"content\":\"Name the capital of France.\"}]}" \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
message = body['choices'][0]['message']
print('answer:', message['content'].strip())
print('reasoning words:', len((message.get('reasoning_content') or '').split()))
print('usage:', body.get('usage'))
"
