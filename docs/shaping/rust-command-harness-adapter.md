# Rust Command Harness Adapter

Snapshot date: 2026-06-18.

Backlog 009 adds `CommandHarness` in `crates/cerberus-adapter/`. The adapter is
the subprocess bridge behind `cerberus_core::ReviewHarness`; it does not move
shell execution or provider semantics into `cerberus-core`.

## Protocol

For each reviewer, `CommandHarness` writes:

```json
{
  "reviewer": "<ReviewerConfig>",
  "request": "<ReviewRequest.v1>"
}
```

to a temp input file, then launches:

```text
<command> <configured args...> --input <input.json> --output <output.json>
```

The command must write a `ReviewerArtifact.v1` JSON document to the output path.
Core then validates identity, coverage, verdict consistency, and aggregation.

## Failure Semantics

- non-zero exit -> `HarnessRuntimeError::Failed`, including bounded stderr
- timeout -> `HarnessRuntimeError::Timeout`
- missing or invalid output JSON -> `HarnessRuntimeError::Failed`

`cerberus-core` converts these runtime errors into degraded reviewer artifacts
when the adapter is used through `review_with_harness`.

## Runtime Hygiene

`CommandHarness` writes the request envelope, output JSON, stdout, and stderr
under an owned temp directory with private permissions and removes the directory
when review returns. On Unix, each command starts in a new process group; timeout
handling sends `SIGTERM`, waits briefly, then sends `SIGKILL` to that process
group before reaping the wrapper.

This is subprocess cleanup, not a sandbox boundary. Commands that daemonize,
call `setsid`, or otherwise leave the process group are unsupported until a
stronger runner containment layer exists. Output JSON, stdout, and stderr files
are private and removed, but their on-disk size is not capped while the command
is running; noisy or adversarial reviewer commands need a later IO-cap slice.

## Verification

```bash
cargo test --workspace command_harness
```

The deterministic fixture command covers successful artifact emission, non-zero
exit, bounded failure diagnostics, timeout, TERM-ignoring descendants, private
temp cleanup, and meaningful reviewer/request envelope checks. It deliberately
does not call Pi, Goose, OpenCode, OMP, or a paid provider.
