#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PORT=${PORT:-5000}
TUNNEL_LOG=$(mktemp "${TMPDIR:-/tmp}/mm-tunnel.XXXXXX")
APP_PID=
TUNNEL_PID=

if [ -n "${PYTHON:-}" ]; then
  PYTHON_CMD=$PYTHON
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  PYTHON_CMD="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_CMD=python3
fi

ensure_python_deps() {
  if ! command -v jq >/dev/null 2>&1; then
    printf '%s\n' "Missing required command: jq" >&2
    printf '%s\n' "Install it with:" >&2
    printf '%s\n' "  sudo apt update && sudo apt install -y jq" >&2
    return 1
  fi

  if "$PYTHON_CMD" - <<'PY' >/dev/null 2>&1
import flask
PY
  then
    return 0
  fi

  printf '%s\n' "Missing Python dependency: Flask" >&2
  printf '%s\n' "Install dependencies with:" >&2
  printf '  %s\n' "$PYTHON_CMD -m pip install -r $PROJECT_ROOT/requirements.txt" >&2
  return 1
}

cleanup() {
  if [ -n "$APP_PID" ]; then
    kill "$APP_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "$TUNNEL_PID" ]; then
    kill "$TUNNEL_PID" >/dev/null 2>&1 || true
  fi
  rm -f "$TUNNEL_LOG"
}

trap cleanup EXIT INT TERM HUP

start_tunnel() {
  if command -v cloudflared >/dev/null 2>&1; then
    cloudflared tunnel --url "http://127.0.0.1:$PORT" > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    return 0
  fi

  if command -v ngrok >/dev/null 2>&1; then
    ngrok http "$PORT" --log=stdout > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    return 0
  fi

  if command -v npx >/dev/null 2>&1; then
    npx --yes cloudflared tunnel --url "http://127.0.0.1:$PORT" > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    return 0
  fi

  printf '%s\n' "No tunnel command found. Install cloudflared or ngrok, or run with MM_PUBLIC_BASE_URL=https://your-public-url" >&2
  return 1
}

wait_for_tunnel_url() {
  tries=0
  while [ "$tries" -lt 90 ]; do
    public_url=$(sed -nE 's/.*(https:\/\/[a-zA-Z0-9.-]+trycloudflare\.com).*/\1/p; s/.*url=(https:\/\/[^ ]+).*/\1/p; s/.*(https:\/\/[a-zA-Z0-9.-]+\.ngrok-free\.app).*/\1/p' "$TUNNEL_LOG" | tail -n 1)
    if [ -n "$public_url" ]; then
      printf '%s' "$public_url"
      return 0
    fi
    if [ -n "$TUNNEL_PID" ] && ! kill -0 "$TUNNEL_PID" >/dev/null 2>&1; then
      printf '%s\n' "Tunnel process stopped before a public URL was created." >&2
      sed -n '1,120p' "$TUNNEL_LOG" >&2
      return 1
    fi
    tries=$((tries + 1))
    sleep 1
  done

  printf '%s\n' "Timed out waiting for tunnel URL." >&2
  sed -n '1,160p' "$TUNNEL_LOG" >&2
  return 1
}

ensure_python_deps

if [ -n "${MM_PUBLIC_BASE_URL:-}" ]; then
  PUBLIC_URL=${MM_PUBLIC_BASE_URL%/}
else
  printf '%s\n' "Starting public HTTPS tunnel for mobile QR access..." >&2
  start_tunnel
  PUBLIC_URL=$(wait_for_tunnel_url)
fi

printf '%s\n' "Mobile public URL: $PUBLIC_URL" >&2
printf '%s\n' "Admin UI: http://127.0.0.1:$PORT" >&2

(
  cd "$PROJECT_ROOT"
  MM_PUBLIC_BASE_URL="$PUBLIC_URL" PORT="$PORT" "$PYTHON_CMD" src/app.py
) &
APP_PID=$!

wait "$APP_PID"
