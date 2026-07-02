# Document the BYOK path for external callers

Priority: P3 | Status: ready | Estimate: S

## Goal

External users/repos invoking Cerberus should pass their own OpenRouter key
rather than any misty-step-owned key. The mechanism already exists and is
correct; it just isn't documented as a named, discoverable path for that
audience.

## Context

Misty-step's own infra (Bitterblossom) now gives each dispatched agent its
own attributable OpenRouter key rather than forwarding one shared long-lived
key (see bitterblossom backlog 104 and PR misty-step/bitterblossom#940). The
same principle applies one level out: an external caller running Cerberus
against their own repo should never need or use a misty-step key.

The mechanism is already live and correct — README.md's "Agent-native
handoff" section shows the exact path:

```sh
cerberus review-diff --base origin/master --head HEAD \
  --harness opencode --model openrouter/z-ai/glm-5.2 \
  --allow-env OPENROUTER_API_KEY \
  --fail-on fail
```

A caller sets `OPENROUTER_API_KEY` in their own process environment (their
own OpenRouter account/key) before invoking Cerberus, and `--allow-env
OPENROUTER_API_KEY` is what lets that key reach the harness. Nothing in
Cerberus itself is misty-step-specific; the key is 100% caller-supplied. But
this is currently documented only as a side effect of the agent-native
handoff example, not named or indexed as "bring your own key" — someone
scanning the README for "can I use this with my own OpenRouter account"
has no anchor to land on.

## Oracle

- [ ] README has an explicit, findable BYOK section (or a clearly labeled
      subsection under "Agent-native handoff") stating: Cerberus never ships
      or requires a misty-step OpenRouter key; callers supply their own via
      `OPENROUTER_API_KEY` + `--allow-env OPENROUTER_API_KEY`.
- [ ] The section cross-references the untrusted-PR scoped-key path
      (`--openrouter-scoped-key` / `--openrouter-provisioning-key-env`) for
      callers who want their own key minted-and-capped per review rather than
      forwarded wholesale — same BYOK principle, stronger isolation.
- [ ] No behavior change — this is a documentation-only ticket.

## Non-goals

Do not add a new flag or env var name for this — `OPENROUTER_API_KEY` +
`--allow-env` is already the correct, minimal mechanism. This ticket is
purely about making the existing path discoverable and explicitly named.
