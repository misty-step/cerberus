# Walkthrough: `cerberus init` hides interactive API-key entry

## Summary

This lane hardens the `cerberus init` setup flow so the interactive OpenRouter API-key prompt no longer echoes typed characters back into the terminal.

- before: the prompt accepted a secret but did not make hidden entry explicit or enforce a non-echoing input path
- after: the prompt switches stdin into raw mode before prompting, collects the secret without echoing it, then restores the terminal state
- proof: the PR-scoped video shows a side-by-side PTY capture of `origin/master` and this branch receiving the same fake secret input
- protection: a PTY-backed regression test now proves the typed secret never appears in captured terminal output

## Before

- the setup flow relied on a standard line prompt for secret entry
- the secret-sensitive step had no regression test exercising a real TTY/PTY interaction
- a real terminal capture could surface the entered key back to the screen while it was being typed

## After

- `bin/cerberus.js` now uses a raw-mode terminal read for the prompt
- the prompt copy now says `input hidden` so the user knows the setup is behaving intentionally
- `tests/test_cerberus_init_cli.py` adds a PTY integration test that waits for the prompt, types a secret, and asserts that the terminal output never contains that secret
- `walkthrough/pr-373/cli-hidden-api-key-prompt.mp4` now shows the old and new flows side by side using actual PTY-derived output

## Verification

Persistent verification for this path:

```bash
pytest tests/test_cerberus_init_cli.py -q
node --check bin/cerberus.js
```

Observed output on this branch:

```text
$ pytest tests/test_cerberus_init_cli.py -q
.............                          [100%]

============================== 15 passed in 7.29s ==============================

$ node --check bin/cerberus.js
```

Walkthrough artifact:

```text
walkthrough/pr-373/cli-hidden-api-key-prompt.mp4
walkthrough/pr-373/reviewer-evidence.md
```

## Why This Is Better

The old setup path asked users to trust a secret prompt without giving them much reason to. This change fixes the trust break at the exact point where users are deciding whether the scaffolder is safe to use, and it leaves behind both an automated PTY regression check and a watchable before/after artifact so the hidden-input behavior stays easy to verify.
