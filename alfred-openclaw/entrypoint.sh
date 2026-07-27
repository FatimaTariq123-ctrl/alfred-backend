#!/bin/sh
set -e

# Run onboard in background once gateway is healthy
if [ -n "$GEMINI_API_KEY" ]; then
  (
    for i in $(seq 1 30); do
      if curl -sf http://localhost:18789/health >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    if [ ! -f "/home/node/.openclaw/agents/main/agent/openclaw-agent.sqlite" ] || \
       ! grep -sq "google" "/home/node/.openclaw/agents/main/agent/openclaw-agent.sqlite" 2>/dev/null; then
      OPENCLAW_GATEWAY_URL=http://localhost:18789 \
        openclaw onboard --non-interactive --accept-risk \
          --mode local \
          --auth-choice gemini-api-key \
          --gemini-api-key "$GEMINI_API_KEY" >/dev/null 2>&1 || true
      # Fix bind back to lan after onboard resets it
      python3 -c "
import json
with open('/home/node/.openclaw/openclaw.json') as f:
    c = json.load(f)
c['gateway']['bind'] = 'lan'
with open('/home/node/.openclaw/openclaw.json', 'w') as f:
    json.dump(c, f, indent=2)
" 2>/dev/null || true
    fi
  ) &
fi

exec tini -s -- node openclaw.mjs gateway
