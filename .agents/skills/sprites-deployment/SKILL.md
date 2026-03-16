# Sprites Deployment

Best practices for deploying Elixir/OTP applications to Fly.io Sprites. Derived from Bitterblossom production patterns and Cerberus deployment experience.

## When to Use

- Deploying or updating an Elixir app on a Sprite
- Provisioning new Sprites (bootstrap)
- Managing secrets, checkpoints, health checks
- Designing CI/CD for Sprite-hosted services
- Debugging Sprite connectivity or process issues

## Sprite CLI Reference

```bash
# Auth
sprite login                          # Browser-based Fly.io auth
sprite login -o my-org                # Org-scoped login
sprite auth setup --token "..."       # Token-based (CI/headless)
sprite org auth                       # Add org API token

# Lifecycle
sprite create <name>                  # Create new sprite
sprite -s <name> exec -- <cmd>        # Execute command
sprite -s <name> console              # Interactive shell
sprite destroy <name>                 # Destroy sprite
sprite list                           # List all sprites

# Checkpoints (snapshot VM state)
sprite -s <name> checkpoint create --comment "description"
sprite -s <name> checkpoint list
sprite restore <checkpoint-id>        # Restore from checkpoint

# Networking
sprite -s <name> url                  # Show public URL
sprite -s <name> url update public    # Make URL public
sprite -s <name> url update --auth bearer  # Require auth
sprite proxy <local>:<remote>         # Port forwarding

# File transfer
sprite -s <name> exec -file local/path:/remote/path -- <cmd>
```

## Architecture Patterns

### CLI-first, not SDK

BB's production conductor uses `sprite` CLI via `Shell.cmd/3`, not a library:

```elixir
# Conductor.Sprite — deep module hiding all sprite protocol
def exec(sprite, command, opts \\ []) do
  timeout = Keyword.get(opts, :timeout, 60_000)
  org = Keyword.get(opts, :org, Config.sprites_org!())
  Shell.cmd("sprite", ["-o", org, "-s", sprite, "exec", "bash", "-lc", command],
    timeout: timeout)
end
```

This is the right approach. The `sprite` CLI handles auth, retries, and protocol evolution. Libraries (`sprites-go`, `sprites-ex`) exist but the CLI is the stable contract.

### Checkpoint Strategy

Checkpoints snapshot the entire VM filesystem. Use them as deployment gates:

1. **Base runtime checkpoint** — after installing Erlang/Elixir/system deps
2. **Deploy checkpoint** — after each code sync + compile
3. **Known-good checkpoint** — after verifying the app starts and health check passes

```bash
# After bootstrap
sprite -s $NAME checkpoint create --comment "base runtime: erlang+elixir"

# After deploy
sprite -s $NAME checkpoint create --comment "deploy $(date +%Y%m%d-%H%M)"
```

Checkpoints are your rollback mechanism. If a deploy breaks, `sprite restore <id>`.

### Secrets Management

**Never pass secrets via CLI args or environment variable injection at exec time.**

BB pattern: persist secrets to a file on the sprite, source at startup:

```bash
# Write secrets file (chmod 600)
cat > /home/sprite/.cerberus-env << 'EOF'
export PORT=8080
export CERBERUS_API_KEY="..."
export CERBERUS_OPENROUTER_API_KEY="..."
export CERBERUS_DB_PATH=/home/sprite/data/cerberus.sqlite3
export CERBERUS_REPO_ROOT=/home/sprite/cerberus
EOF
chmod 600 /home/sprite/.cerberus-env

# Source at startup
. /home/sprite/.cerberus-env
```

Secrets survive checkpoints (they're on the filesystem). Update by overwriting the file and restarting.

### Health Checks

Layered health probing pattern from BB conductor:

```elixir
def status(sprite, opts \\ []) do
  # Layer 1: Reachability (echo ok, 15s timeout)
  case probe(sprite) do
    {:ok, %{reachable: true}} ->
      # Layer 2: Runtime ready (command -v elixir)
      # Layer 3: App healthy (curl localhost:PORT/api/health)
      # Layer 4: Auth ready (gh auth status) — if GitHub ops needed
      {:ok, %{sprite: sprite, reachable: true, healthy: all_checks_pass}}
    {:error, reason} -> {:error, reason}
  end
end

defp probe(sprite) do
  case exec(sprite, "echo ok", timeout: 15_000) do
    {:ok, _} -> {:ok, %{reachable: true}}
    {:error, msg, _} -> {:error, msg}
  end
end
```

### Process Management

Before dispatching work, always kill stale processes:

```elixir
@agent_process_names ~w(beam elixir)

defp kill_stale_cmd do
  @agent_process_names
  |> Enum.map_join("; ", &"pkill -9 -f #{&1} 2>/dev/null")
  |> Kernel.<>("; true")  # Always succeed
end
```

Check if sprite is busy before dispatch:

```elixir
def busy?(sprite) do
  case exec(sprite, "pgrep -f 'mix run' 2>/dev/null", timeout: 15_000) do
    {:ok, output} -> String.trim(output) != ""
    _ -> false
  end
end
```

### File Sync Pattern

Use `-file` flag for bulk transfers, not `echo | base64`:

```bash
sprite -s $NAME exec \
  -file ./cerberus-elixir/:/home/sprite/cerberus-elixir/ \
  -file ./defaults/:/home/sprite/cerberus/defaults/ \
  -file ./pi/:/home/sprite/cerberus/pi/ \
  -file ./templates/:/home/sprite/cerberus/templates/ \
  -- sh -c 'cd /home/sprite/cerberus-elixir && MIX_ENV=prod mix deps.get --only prod && MIX_ENV=prod mix compile'
```

For single files (prompts, configs), base64 encoding avoids shell quoting:

```elixir
encoded = Base.encode64(content)
exec(sprite, "echo #{encoded} | base64 -d > '#{path}'", timeout: 30_000)
```

### Workspace Layout

Standard directory structure on a Cerberus sprite:

```
/home/sprite/
├── .cerberus-env           # Secrets (chmod 600)
├── cerberus-elixir/        # Elixir application source
│   ├── _build/
│   ├── deps/
│   └── ...
├── cerberus/               # Shared OSS assets
│   ├── defaults/           # config.yml, reviewer-profiles.yml
│   ├── pi/agents/          # Perspective system prompts
│   └── templates/          # Prompt templates
└── data/
    └── cerberus.sqlite3    # Persistent SQLite database
```

### Auth Token Priority

```
1. SPRITE_TOKEN (direct, no exchange) — preferred for CI
2. FLY_API_TOKEN → exchanged to SPRITE_TOKEN via macaroon
3. sprite login → stored in ~/.sprites/sprites.json
```

For CI/CD, use `SPRITE_TOKEN` directly. For local dev, use `sprite login`.

## Anti-Patterns

- **Don't use `mix release` on sprites** — sprites have the full runtime; `mix run --no-halt` is simpler and enables hot code reload during development
- **Don't inject secrets via exec environment** — they show up in process tables and logs; use persisted env files
- **Don't skip checkpoints** — they're your rollback mechanism and cost nothing
- **Don't use `--sname` in production** — it's fine for single-node, but if you ever cluster, use `--name` with a FQDN
- **Don't deploy without a health check** — always verify `/api/health` returns 200 after deploy before checkpointing

## CI/CD Pattern

```yaml
# .github/workflows/deploy.yml
name: Deploy to Sprite
on:
  push:
    branches: [master]
    paths: ['cerberus-elixir/**', 'defaults/**', 'pi/**', 'templates/**']

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install sprite CLI
        run: curl -fsSL https://sprites.fly.dev/install | sh

      - name: Auth
        run: sprite auth setup --token "${{ secrets.SPRITE_TOKEN }}"

      - name: Deploy
        run: ./cerberus-elixir/deploy-sprite.sh deploy

      - name: Health check
        run: |
          URL=$(sprite -s cerberus-api url)
          curl -sf "$URL/api/health" || exit 1

      - name: Checkpoint
        if: success()
        run: sprite -s cerberus-api checkpoint create --comment "ci-deploy-${{ github.sha }}"
```
