# Environment

Environment variables, external dependencies, and setup notes.

**What belongs here:** required env vars, external tool dependencies, packaging/runtime notes, platform-specific setup.
**What does NOT belong here:** service ports or long-running process commands (use `.factory/services.yaml`).

---

- Primary toolchain: Elixir 1.19 / OTP 28, `mix`, `git`, `rg`
- Optional helper for package-path validation: Docker is available locally, but the target product must not require Docker at runtime
- Mission target is CLI-only: no HTTP server, database, Sprite, or GitHub Action control plane
- Current repo starts with the Elixir app nested under `cerberus-elixir/`; workers are expected to move it to repo root during the final simplification milestone
- Real end-user review runs will need provider credentials, but mission validation should use deterministic doubles/fixtures instead of live provider calls
