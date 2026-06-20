# Harden execution and evidence admission before automatic review

Priority: P0 | Status: ready | Estimate: L

## Goal

Make Cerberus safe to run as a primary review agent by enforcing the local gate
in CI, removing parent-`PATH` executable selection risk, and rejecting
semantically inconsistent review artifacts.

## Oracle

- [ ] A GitHub workflow runs `./scripts/verify.sh` on pull requests and pushes.
- [ ] Harness execution resolves OpenCode/OMP binaries from an explicit trusted
  search policy or absolute paths, not the parent process `PATH`.
- [ ] Artifact validation rejects unknown `finding_id` links, unknown
  `suggested_fixes` references, orphan top-level fixes, and duplicate
  artifact blocks across all accepted extraction formats.
- [ ] Adversarial fixture tests prove the gate fails for each case above.

## Verification System

- Claim: Cerberus cannot be tricked into executing an unexpected substrate
  binary or accepting malformed cross-linked review artifacts, and the repo
  gate runs in hosted CI.
- Falsifier: a hostile `PATH` fixture selects a fake `opencode`; a comment or
  fix references a missing finding and passes validation; a transcript with
  two artifact candidates is accepted; a PR can merge without the repo gate.
- Driver: `./scripts/verify.sh` locally and the GitHub Actions workflow on a
  pull request.
- Grader: Rust unit tests, fixture harness smoke, CI check result, and a saved
  failure transcript for adversarial artifact extraction.
- Evidence packet: `target/cerberus/*`, GitHub workflow URL, and failing-then-
  passing test names.
- Cadence: every PR touching harness, validation, prompt, request acquisition,
  or CI.

## Children

1. Add `.github/workflows/verify.yml` that runs `./scripts/verify.sh`.
2. Replace parent-`PATH` lookup with a controlled resolver and tests for hostile
   `PATH` substitution.
3. Strengthen artifact cross-reference validation for findings, comments,
   citations, and suggested fixes.
4. Make artifact extraction strict about multiple candidates across marker,
   XML, and raw JSON fallback modes.
5. Add one adversarial fixture per falsifier and document the threat model in
   `spec.md`.

## Notes

**Why:** The security lane confirmed no `.github` workflow exists, while
`src/harness.rs` resolves binaries from the parent `PATH` before child env
sanitization and `src/validation.rs` does not yet cross-check all comment/fix
IDs. This is the best next pickup because it protects every later posting or
automation path.
