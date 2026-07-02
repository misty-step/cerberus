# Cerberus repo contracts

- North star: read `VISION.md` before changing review scope, artifact shape,
  reviewer topology, caller boundaries, or runtime/substrate assumptions.
- Product contract: `spec.md` is the locked MVP contract. Architectural
  decisions live in `docs/adr/`.
- Cerberus is the opinionated code-review harness. It accepts arbitrary review
  context, usually a base/head diff, and produces a validated
  `ReviewArtifact.v1` that can stand alone or be projected into GitHub.
- Keep the core caller-neutral. Local runs, CI, GitHub Actions, Olympus,
  Bitterblossom, or another plane may trigger Cerberus; none of those should
  become the product boundary.
- The master reviewer may choose dynamic subagent lanes at runtime. Do not
  hardcode a static persona fleet into Rust.
- Review quality improves through evals and receipts. Cost, model choice,
  prompt shape, tool access, and subagent topology are optimization variables,
  not constants to hide in product code.

## Gate

Run before claiming repo changes are complete:

```sh
./scripts/verify.sh
```

For docs-only changes, still run the gate unless the failure is an unrelated
environment issue; report the exact command and residual risk.

`verify.sh` also runs a `gitleaks` secret scan over the working tree and the
diff against `origin/master` (skipped, not failed, if `gitleaks` isn't
installed locally — CI always has it). A finding fails the gate; there is no
allowlist mechanism today, so a true positive must be removed, not suppressed.

## Red lines

These four are load-bearing product rules, not style preferences:

1. **No static reviewer roster in Rust.** The master reviewer chooses lane
   topology (correctness/security/whatever) at runtime from the diff; no
   fixed persona list is ever hardcoded into product code. This is a design
   review discipline, not something a unit test can catch — enforce it in
   code review, not by looking for a passing test.
2. **No prompt or diff content in argv.** Prompts and request bodies are
   written to private tempfiles and referenced by path or piped in, never
   passed as command-line arguments (which are visible to any other process
   on the host via `ps`). Pinned by
   `harness::tests::redacts_prompt_file_from_execution_plan_args`.
3. **No ambient credential inheritance.** Every substrate child process gets
   `env_clear()`-ed and then only the explicit `--allow-env` allowlist copied
   back in — nothing else leaks from the Cerberus process's own environment.
   Pinned by `harness::tests::child_env_uses_only_allowlist`.
4. **`spec.md` is the locked MVP contract.** Changing the `ReviewRequest.v1`/
   `ReviewArtifact.v1` shape, the kernel seam, or a locked invariant needs an
   ADR in `docs/adr/`, not a quiet edit. This is a governance rule, not a
   test — a PR that changes the schema without a matching ADR should be
   rejected in review.

Substrate binaries (opencode/omp/docker/gh/git) are resolved either from an
explicit absolute path or from a fixed trusted search path, never a bare name
trusted to whatever's first on `$PATH` — see
`harness::trusted_executable_search_path`, pinned by
`harness::tests::bare_substrate_binary_resolves_only_from_trusted_search_path`
and `relative_substrate_binary_paths_are_rejected`.

## Live-review prerequisites

`verify.sh` and `cargo test` only ever exercise the `fixture` substrate and
fake `opencode`/`omp`/`gh`/`docker` binaries under `fixtures/bin/` — a fully
green gate proves the contract layer, not that a live model-backed review
actually works. To run `--harness opencode` (the default) against a real
model, you need, beyond what the gate checks:

- `opencode` installed and on `$PATH` (or one of the trusted search path
  locations below), new enough to support `run --format json --session` and
  file-based artifact emission (the substrate contract this repo drives).
  **No specific version is pinned anywhere in this repo today** — that's a
  known gap, not a documented requirement; if you hit a substrate-contract
  mismatch, that's the first thing to suspect.
- `OPENROUTER_API_KEY` set and passed through explicitly (`--allow-env
  OPENROUTER_API_KEY`, or `--openrouter-scoped-key` — backlog 013 M1 — which
  mints a short-lived capped key instead of forwarding a long-lived one).
- `--model openrouter/<provider>/<model-id>` naming a real, reachable model.
- For `review-pr`: `gh` installed, and an explicit token via `--gh-token-file`
  or `--gh-token-env` (ambient `gh auth login` state is never used for reads
  or posting — see `resolve_github_token` in `src/main.rs`).
- For `--harness container-opencode` (backlog 013 M2, untrusted-PR isolation):
  a reachable Docker daemon. `verify.sh`'s container red-team block is
  Docker-gated (skipped, not failed, when `docker info` fails), so a green
  gate does not prove this path works either.

Binaries resolve from an absolute path or from
`harness::trusted_executable_search_path`: `/usr/bin`, `/bin`, `/usr/sbin`,
`/sbin`, `/opt/homebrew/bin` and `/usr/local/bin` (if present), and
`$HOME/.bun/bin`, `$HOME/.opencode/bin`, `$HOME/.local/bin` (if present). A
bare name anywhere else — even if it's genuinely on `$PATH` — is rejected;
pass an absolute path via the matching `--*-binary` flag instead.
