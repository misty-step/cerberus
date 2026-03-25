#!/usr/bin/env bash
set -euo pipefail

REPO="/Users/phaedrus/Development/cerberus-mono/cerberus"
APP="$REPO/cerberus-elixir"

if [ -f "$REPO/mix.exs" ]; then
  APP="$REPO"
fi

cd "$APP"

mix local.hex --force >/dev/null 2>&1 || true
mix local.rebar --force >/dev/null 2>&1 || true
mix deps.get
