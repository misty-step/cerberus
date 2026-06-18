# Rust Local Review Replay

Snapshot date: 2026-06-18.

Backlog 013 adds `cerberus-cli review-local`, a Rust local-review entrypoint
that reads a checked git-style diff fixture, builds `ReviewRequest.v1`, runs the
Rust review core, and writes the same artifact surfaces as `cerberus-cli review
--fixture`.

## CLI Contract

```bash
cargo run --locked -p cerberus-cli -- review-local \
  --diff-file fixtures/local-review/local.diff \
  --out tmp/local-review
```

Optional flags:

- `--config <review-config.json>` overrides the default fake panel.
- `--repo-path <path>` records the local source path on the request.
- `--request-id <id>` overrides the generated `local-diff-<stem>` id.
- `--title <title>` overrides the default local review title.

The command writes:

- `review-request.json`
- `review-run-artifact.json`
- `review-run.md`

## Diff Boundary

The parser is syntax-level only. It accepts `diff --git` headers, status
markers such as `new file mode`, `deleted file mode`, `rename to`, and `copy to`,
and hunk `+` / `-` counts. It rejects empty input, diffs that do not start with a
header, unsupported whitespace in header paths, and duplicate output paths.

The parser does not shell out to Git, inspect the working tree, choose reviewer
personas, or classify semantic intent. Reviewer behavior remains owned by
`cerberus-core` and configured harnesses.

## Verification

```bash
cargo test --workspace local_review
cargo run --locked -p cerberus-cli -- review-local --diff-file fixtures/local-review/local.diff --out tmp/local-review
cargo run --locked -p cerberus-cli -- validate tmp/local-review/review-request.json
cargo run --locked -p cerberus-cli -- validate tmp/local-review/review-run-artifact.json
```

The checked fixture contains the exact `CERBERUS_FAKE_FINDING` directive, so the
default deterministic Rust reviewer emits one fixture finding. That proves
artifact plumbing and local diff metadata, not live model quality.

## Retirement Boundary

This is partial parity for the legacy Elixir local review command. It moves
local diff replay into Rust, but legacy reviewer routing, hosted API
compatibility, live provider execution, and persistent review state still remain
pending retirement surfaces.
