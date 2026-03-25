# Environment

Environment variables, external dependencies, and setup notes.

**What belongs here:** required env vars, external tool dependencies, packaging/runtime notes, platform-specific setup.
**What does NOT belong here:** service ports or long-running process commands (use `.factory/services.yaml`).

---

- Primary toolchain: Elixir 1.19 / OTP 28, `mix`, `git`, `rg`
- Optional helper for package-path validation: Docker is available locally, but the target product must not require Docker at runtime
- Mission target is CLI-only: no HTTP server, database, Sprite, or GitHub Action control plane
- The Mix application now lives at the repository root; root-level `mix compile --warnings-as-errors`, `mix test`, `mix format --check-formatted`, and `mix escript.build` are the supported validation commands
- The current packaged CLI lane is `mix escript.build`; `mix.exs` sets `app: nil` for the escript so `cerberus --help` and retired-command failures do not boot the application supervisor or emit runtime noise
- Real end-user review runs will need provider credentials, but mission validation should use deterministic doubles/fixtures instead of live provider calls
- For terminal-only manual checks, prefer the built `./cerberus` escript or `mix cerberus.review ...`; no supported workflow should require a long-running service.
