#!/usr/bin/env bash
# Independent diagnostic CLI; not the Windows single-instance bridge.
set -euo pipefail
PROXY_PORT=${1:-18789}
MODE=${2:-cli}
WITH_BRIDGE=${3:-false}
TEST_HOME=${4:?Usage: start-tap.sh PORT cli-or-proxy-only true-or-false ABSOLUTE_TEST_HOME [UPSTREAM]}
UPSTREAM=${5:-http://127.0.0.1:17841/v1}
command -v claude-tap >/dev/null || { echo 'Install claude-tap==0.1.145 first.' >&2; exit 1; }
[[ "$MODE" == cli || "$MODE" == proxy-only ]] || { echo 'Unsupported mode' >&2; exit 1; }
[[ "$WITH_BRIDGE" == true || "$WITH_BRIDGE" == false ]] || exit 1
[[ "$PROXY_PORT" =~ ^[0-9]+$ ]] && (( PROXY_PORT > 0 && PROXY_PORT < 65536 )) || exit 1
[[ "$TEST_HOME" == /* && -f "$TEST_HOME/config.toml" ]] || { echo 'Prepare an absolute TEST_HOME with config.toml first.' >&2; exit 1; }
test_root=$(cd "$TEST_HOME" && pwd -P)
normal_home=${CODEX_HOME:-$HOME/.codex}
if [[ -d "$normal_home" ]] && [[ "$test_root" == "$(cd "$normal_home" && pwd -P)" ]]; then
    echo 'TEST_HOME must differ from the normal CODEX_HOME.' >&2; exit 1
fi
args=(--tap-client codex --tap-host 127.0.0.1 --tap-port "$PROXY_PORT" --tap-live)
[[ "$WITH_BRIDGE" == true ]] && args+=(--tap-target "$UPSTREAM")
[[ "$MODE" == proxy-only ]] && args+=(--tap-no-launch --tap-proxy-mode reverse)
echo "Diagnostic home: $test_root; listener: 127.0.0.1:$PROXY_PORT"
echo 'Close the client first; use Ctrl+C in this foreground proxy terminal.'
# Scoped to the child only; preserve the parent shell and upstream proxy environment.
CODEX_HOME="$test_root" claude-tap "${args[@]}"
