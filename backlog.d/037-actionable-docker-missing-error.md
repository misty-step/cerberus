# Actionable error when Docker is missing or misconfigured for container-opencode

Priority: P2 · Status: ready · Estimate: S

## Goal
`run_docker_with_timeout` (`src/container.rs:699`) spawns `docker run` via
`command.spawn().context("spawn docker run")?` — if the docker binary is
missing or misnamed, the operator sees a bare `spawn docker run: No such file
or directory (os error 2)` instead of an actionable message naming the fix,
unlike the parallel `git`/`gh` binary-missing path backlog 009 already fixed
(`src/request.rs:744-758`, `missing_binary_names_the_install_or_flag_fix`).

## Oracle
- [ ] A `docker run` spawn failure (binary not found) surfaces an error naming:
      install Docker, or point `--container-binary` at the correct executable —
      mirroring the existing `--*-binary` pattern in `request.rs`.
- [ ] A new unit test in `container.rs` exercises `run_docker_with_timeout` (or
      its caller) with a nonexistent binary name and asserts the error message
      names the fix, following the shape of
      `request.rs::missing_binary_names_the_install_or_flag_fix`.
- [ ] No change to behavior when Docker is present and working.
- [ ] `./scripts/verify.sh` green.

## Notes
Verified live 2026-07-01: `container.rs:699`
(`child = command.spawn().context("spawn docker run")?`) has no docker-missing
test among its 14 `#[test]` functions (checked by name — none named
`missing`/`not_found`/similar for the docker binary itself, only
`parse_host_port_rejects_missing_port`). The `--container-binary` flag already
exists (`main.rs`) as the fix path — the flag exists, the error just doesn't
point to it yet.

**Why:** OVERNIGHT.md's cerberus focus line ("tests + docs hardening around
the M1/M2 credential+container path") plus the precedent 009 already set for
every other missing-binary path in this codebase; this substrate landed after
009 and never got the same treatment.
