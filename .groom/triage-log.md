# Reviewer Delta Triage Log

Append-only log of Cerberus vs external reviewer comparisons. One entry per PR.
Miss patterns that repeat across entries become hardening work.

---

### PR #401 — Implement persona registry and config system

**Date:** 2026-03-15 | **Link:** https://github.com/misty-step/cerberus/pull/401 | **Verdict:** WARN
**Ran:** trace/correctness (PASS 1.0), guard/security (PASS 0.8), proof/testing (FAIL 0.95) | **Timed out:** guard, trace (initial run only) | **Skipped:** atlas, fuse, craft (wave2/3 gated)

#### Misses

| Finding | Category | Perspective | Blind/Impaired | Found by | Lever |
|---------|----------|-------------|----------------|----------|-------|
| Empty prompt `""` fallback violates Persona invariant | invariant-violation | correctness | blind | Greptile, Codex | prompt |
| `raise` inside `with` chain crashes GenServer on missing prompt | genserver-lifecycle | correctness | blind | Greptile | prompt |
| `reload/0` swallows errors, returns `:ok` on failure | error-handling | correctness | blind | Greptile, CodeRabbit, Codex | prompt |
| Hot-reload only checks known files, blind to new prompt additions | logic-gap | correctness | blind | Greptile | prompt |
| TOCTOU race between `File.read` and `File.stat` in prompt loading | race-condition | correctness | blind | Greptile | prompt, eval |
| Empty (0-byte) prompt file bypasses invariant guard | invariant-violation | correctness | blind | Greptile | prompt |
| Silent error discard in poll-path reload | error-handling | correctness | blind | CodeRabbit, Cerberus/correctness (later run) | prompt |

#### Cerberus-only finds

| Finding | Perspective | Category |
|---------|-------------|----------|
| Hot-reload test is tautological (touches mtime, asserts unchanged content) | testing | assertion-quality |
| No test for hot-reload on added/removed prompt files | testing | missing-coverage |
| No test for missing/empty persona prompt errors during init/reload | testing | missing-coverage |
| No test for `normalize_repo_root` parent directory fallback | testing | missing-coverage |
| No test for Router queries Config after decoupling | testing | missing-coverage |

#### Noise

| Finding | Reviewer | Why noise |
|---------|----------|-----------|
| `String.to_atom/1` risks atom table exhaustion | Greptile, CodeRabbit | Developer-controlled config, 6 bounded atoms, loaded once |
| `\|\|` overrides intentional falsy/zero values | Greptile | `panel_size: 0` is not a valid config |
| Missing `on_exit` for background poll timer | Greptile | Linked process; BEAM drops messages to dead PIDs |
| Add comment on shuffle-per-call behavior | CodeRabbit | Intent clear from test name |
| Shuffle test flake note | CodeRabbit | Fallback handles edge case |

#### Signal quality

| Reviewer | Findings | Real | Noise | Unique (not found by others) |
|----------|----------|------|-------|------------------------------|
| Greptile | 12 | 9 | 3 | 5 (raise-crashes-GS, new-file-blind, TOCTOU, empty-file, poll-error) |
| CodeRabbit | 6 | 3 | 3 | 1 (moduledoc stale) |
| Codex | 2 | 2 | 0 | 0 (all duplicates of Greptile) |
| Cerberus/proof | 5 | 5 | 0 | 5 (all test-quality findings unique to Cerberus) |
| Cerberus/trace | 0 | 0 | 0 | 0 |
| Cerberus/guard | 0 | 0 | 0 | 0 |

#### Patterns

- **correctness/trace: blind to GenServer lifecycle bugs.** `raise` inside `with`, error-swallowing in callbacks, `{:stop, reason}` vs exception semantics — trace passed at 1.0 confidence while the code had 6+ real correctness bugs. This is the biggest gap.
- **correctness/trace: blind to struct invariant violations.** Moduledoc says "never empty" but code defaults to `""`. Trace should check documented invariants against implementation.
- **correctness/trace: blind to TOCTOU races.** `File.read` then `File.stat` as separate syscalls. Narrow window but real.
- **testing/proof: strongest perspective.** 5/5 real, 5/5 unique. Found tautological assertions and missing error-path tests that no external reviewer caught.
- **Greptile: highest signal external reviewer.** 9/12 real, 5 unique. Consistently finds implementation bugs that Cerberus correctness misses.
- **Codex: no unique signal.** 2/2 real but both duplicates of Greptile. Low marginal value.
