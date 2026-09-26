#!/usr/bin/env bash
set -euo pipefail
PROXY_PORT=${1:-18789}
echo 'Close the diagnostic client, then use Ctrl+C in the proxy terminal.'
if command -v lsof >/dev/null; then lsof -nP -iTCP:"$PROXY_PORT" -sTCP:LISTEN || true; fi
echo 'Inspection only. No unverified process is killed. To stop the shared viewer explicitly:'
echo 'claude-tap dashboard stop'
