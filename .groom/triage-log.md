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

---

### PR #404 — Port verdict aggregation and finding dedup to Elixir

**Date:** 2026-03-15 | **Link:** https://github.com/misty-step/cerberus/pull/404 | **Verdict:** WARN
**Ran:** trace/correctness (PASS 1.0, WARN 0.95), guard/security (PASS 1.0, PASS 0.92), proof/testing (PASS 0.90), atlas/architecture (PASS 0.85, PASS 0.92) | **Timed out:** none | **Skipped:** fuse, craft

#### Misses

| Finding | Category | Perspective | Blind/Impaired | Found by | Lever |
|---------|----------|-------------|----------------|----------|-------|
| `:low_confidence` reserve signal dead code — can never fire with default `confidence_min=0.7` because verdicts below 0.5 are gated to SKIP first, and `low_confidence?` skips SKIP verdicts | logic-gap | correctness | blind | Codex | eval |

#### Cerberus-only finds

| Finding | Perspective | Category |
|---------|-------------|----------|
| Aggregator returns plain map instead of struct | architecture | api-consistency |
| Model pricing hardcoded in module attribute | architecture | configuration |
| Double-negative logic in `content_match?` reduces clarity | architecture | complex-logic |
| Simple rule-based stemmer may have edge cases | architecture | implementation-choice |

#### Noise

| Finding | Reviewer | Why noise |
|---------|----------|-----------|
| Simplify `build_summary` list-building pattern | Gemini | Style preference, not a defect |
| Remove `prepend_if` helper | Gemini | Style preference, coupled to above |
| Simplify `detect_reserves` pattern | Gemini | Style preference |
| Extract `1_000_000` to named constant | Gemini | Literal is self-evident in `cost / 1_000_000` |
| Simplify `content_tokens` with `flat_map` | Gemini | Style preference |
| Remove "redundant" `List.flatten` after `Regex.scan` | Gemini | **Wrong** — `Regex.scan` without capture groups returns `[["match"]]`, flatten IS needed |
| Consolidate nil/""/null guard clauses | Gemini | Style preference |
| Missing `/council override` backward compatibility | Codex | Deliberately removed for product isolation rule |

#### Signal quality

| Reviewer | Findings | Real | Noise | Unique (not found by others) |
|----------|----------|------|-------|------------------------------|
| Cerberus/trace | 1 | 1 | 0 | 0 (perm atom/string — also found by Codex) |
| Cerberus/atlas | 4 | 2 | 2 | 2 (map-vs-struct, pricing-hardcoded) |
| Cerberus/guard | 0 | 0 | 0 | 0 |
| Cerberus/proof | 0 | 0 | 0 | 0 |
| Gemini | 7 | 0 | 7 | 0 (all style, one factually wrong) |
| Codex | 3 | 2 | 1 | 1 (`:low_confidence` dead code — real miss) |
| Greptile | 0 | — | — | — (paywalled) |
| CodeRabbit | 0 | — | — | — (rate-limited) |

#### Patterns

- **correctness/trace: blind to threshold interaction bugs.** The `:low_confidence` dead code is a logic bug where two thresholds (confidence_min=0.7 for gating, 0.5 for reserve trigger) interact to make one feature permanently unreachable. Trace ran twice (wave1 + wave3) and missed this both times. This is the same class of bug as PR #401: trace fails to reason about the interaction between sequential pipeline stages.
- **Codex: strongest external reviewer here.** 2/3 real, 1 unique (the dead-code logic bug). The `/council` finding was wrong (doesn't know the product isolation rule) but the reserve signal finding is the PR's most important bug. Codex outperformed Gemini on this PR.
- **Gemini: zero signal on inline comments.** 7 inline comments, all style-only, one factually wrong (claimed `List.flatten` was redundant when it's required). No defects found. Gemini was the weakest reviewer on this PR.
- **Permission atom/string mismatch: convergent finding.** Found independently by Cerberus/trace AND Codex. Both correctly identified the integration risk. Cerberus gets credit for catching it but so does Codex.
- **Collector script was silently dropping inline review comments.** The `collect_pr_review_surface.py` script only fetched `comments` and `reviews` via `gh pr view --json`, missing the `pulls/{pr}/comments` REST endpoint entirely. This caused the initial triage to miss 11 inline comments. Fixed by adding `fetch_review_comments()` to the collector.
