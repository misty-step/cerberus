#!/usr/bin/env bash
# Deploy Cerberus Elixir API to a Fly Sprite.
#
# Usage:
#   ./deploy-sprite.sh              # deploy (create Sprite if needed)
#   ./deploy-sprite.sh bootstrap    # force full bootstrap
#   ./deploy-sprite.sh secrets      # set secrets interactively
#   ./deploy-sprite.sh start        # start the app (foreground)
#   ./deploy-sprite.sh restart      # kill stale + start backgrounded (CI/CD)
#
# Requires: sprite CLI, authenticated with Fly.

set -euo pipefail

SPRITE_NAME="${CERBERUS_SPRITE_NAME:-cerberus-api}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MONO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Helpers ---

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

sprite_exists() {
  sprite list 2>/dev/null | grep -q "$SPRITE_NAME"
}

# --- Bootstrap ---

bootstrap() {
  log "Creating Sprite: $SPRITE_NAME"
  sprite create "$SPRITE_NAME"

  log "Installing Erlang/Elixir runtime"
  sprite -s "$SPRITE_NAME" exec -- sh -c '
    apt-get update && apt-get install -y --no-install-recommends erlang elixir git ca-certificates
    mix local.hex --force && mix local.rebar --force
    mkdir -p /home/sprite/data /home/sprite/cerberus
  '

  sprite -s "$SPRITE_NAME" checkpoint create --comment "base runtime"
  sprite -s "$SPRITE_NAME" url update public
  log "Bootstrap complete"
}

# --- Deploy ---

deploy() {
  log "Syncing code to Sprite"
  sprite -s "$SPRITE_NAME" exec \
    -file "$SCRIPT_DIR/":/home/sprite/cerberus-elixir/ \
    -file "$MONO_ROOT/defaults/":/home/sprite/cerberus/defaults/ \
    -file "$MONO_ROOT/pi/":/home/sprite/cerberus/pi/ \
    -file "$MONO_ROOT/templates/":/home/sprite/cerberus/templates/ \
    -- sh -c '
    cd /home/sprite/cerberus-elixir
    MIX_ENV=prod mix deps.get --only prod
    MIX_ENV=prod mix compile
  '

  log "Deploy complete (checkpoint deferred to caller)"
}

# --- Secrets ---

set_secrets() {
  echo "Enter CERBERUS_API_KEY (API auth):"
  read -rs CERBERUS_API_KEY
  echo "Enter CERBERUS_OPENROUTER_API_KEY (LLM calls):"
  read -rs CERBERUS_OPENROUTER_API_KEY

  # Write env file locally, transfer via -file to avoid secrets in process args
  local tmpfile
  tmpfile=$(mktemp)
  trap 'rm -f "$tmpfile"' RETURN

  cat > "$tmpfile" << EOF
export PORT=8080
export CERBERUS_API_KEY=$CERBERUS_API_KEY
export CERBERUS_OPENROUTER_API_KEY=$CERBERUS_OPENROUTER_API_KEY
export CERBERUS_DB_PATH=/home/sprite/data/cerberus.sqlite3
export CERBERUS_REPO_ROOT=/home/sprite/cerberus
EOF

  sprite -s "$SPRITE_NAME" exec \
    -file "$tmpfile":/home/sprite/.cerberus-env \
    -- chmod 600 /home/sprite/.cerberus-env

  log "Secrets written"
}

# --- Start ---

start_app() {
  log "Starting Cerberus API"
  sprite -s "$SPRITE_NAME" exec -- sh -c '
    . /home/sprite/.cerberus-env
    cd /home/sprite/cerberus-elixir
    MIX_ENV=prod elixir --sname cerberus -S mix run --no-halt
  '
}

# --- Restart (CI/CD) ---

restart_app() {
  log "Restarting Cerberus API"
  sprite -s "$SPRITE_NAME" exec -- sh -c '
    # Pattern must match the nohup command below; bracket trick prevents self-match
    pkill -f "[m]ix run --no-halt" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      pgrep -f "[m]ix run --no-halt" > /dev/null || break
      sleep 1
    done
    # Escalate to SIGKILL if graceful shutdown failed
    if pgrep -f "[m]ix run --no-halt" > /dev/null 2>&1; then
      pkill -9 -f "[m]ix run --no-halt" 2>/dev/null || true
      sleep 1
    fi
    . /home/sprite/.cerberus-env
    cd /home/sprite/cerberus-elixir
    nohup sh -c "MIX_ENV=prod elixir --sname cerberus -S mix run --no-halt" \
      > /home/sprite/cerberus.log 2>&1 &
  '
  log "Restart initiated"
}

# --- Main ---

command="${1:-deploy}"

case "$command" in
  bootstrap)
    bootstrap
    deploy
    ;;
  secrets)
    set_secrets
    ;;
  start)
    start_app
    ;;
  restart)
    restart_app
    ;;
  deploy)
    if ! sprite_exists; then
      log "Sprite not found, bootstrapping first"
      bootstrap
    fi
    deploy
    ;;
  *)
    die "Unknown command: $command. Use: deploy, bootstrap, secrets, start, restart"
    ;;
esac
