Yes — **check runs + per‑reviewer PR comments** is the right shape, and it also makes the “blocking merge gate” clean.

Below is what I think is the *ideal design + form factor* given everything you raised: cost, parallelism, real context gathering, multi‑provider/model, and an explicit “override with paper trail” escape hatch.

---

## The simplest “correct” architecture

### The core trick

Use **a single workflow** with:

1. **One job per reviewer (matrix)**

   * Each job = a **check run** in GitHub’s UI (native, no custom Checks API needed unless you want annotations).
   * Each reviewer job:

     * runs the review
     * **posts/updates a PR comment**
     * exits 0/1 → green/red check run

2. **One aggregate job: “Council Verdict”**

   * Always runs (`if: always()`), even if reviewers failed.
   * Reads all reviewer outputs.
   * Computes unanimous pass/fail **unless override**.
   * This is the **only check you mark “required”** in branch protection.

This gives you:

* Visible per‑reviewer PASS/FAIL checks
* Visible per‑reviewer comment reports
* A single required gate check you can override intentionally

GitHub branch protection treats required checks as satisfied when they’re successful (and also counts `skipped` / `neutral` as acceptable in protection rules). ([GitHub Docs][1])

---

## Parallel vs sequential: make it configurable, default to parallel

Your reasoning is sound: with specialized perspectives, **full parallel usually wastes less time** (and often less money) because you fix multiple issues per iteration instead of discovering them one at a time.

In Actions terms:

* `strategy.fail-fast: false` → keep everyone running so you see *all* failures.
* `concurrency: cancel-in-progress: true` keyed on PR number → if the author pushes a new commit, you **cancel the old council run** immediately (this is the biggest cost saver in practice).

If you *do* want the “stop after the first veto” mode sometimes, flip:

* `fail-fast: true` or “tiered reviewers” (cheap tier first, expensive tier later).

---

## The real design question: diff-pack vs agentic repo investigation

You’re right: **diff-only reviewers miss cross-file implications**.

I’d recommend supporting **three context modes**, because there isn’t one mode that’s optimal for every repo / budget / security posture.

### Mode 1: Diff-only (fast, cheap, shallow)

* Input: PR title/body + file list + diff hunks
* Works fine for style, basic correctness, obvious security leaks
* Fails on “semantic” changes and hidden coupling

### Mode 2: Bounded “context request” loop (my default recommendation)

This is the best balance of **agentic context** without giving a model a loaded gun.

Loop (2–3 rounds, hard budget):

1. Send diff-pack + repo index summary
2. Model returns JSON:

   * `files_needed[]`, `search_queries[]`, maybe `symbols_needed[]`
3. Runner fulfills those requests locally (safe file reads + grep), returns snippets
4. Model produces final structured review JSON

This yields most of the benefit of “agentic investigation” while keeping:

* deterministic budgets
* no arbitrary shell execution
* no tool permission YOLO problems

### Mode 3: Full agent CLI (deepest, most “autonomous”)

This is where you run tools like:

* **Kimi Code CLI** (print mode + JSONL output)
* **Gemini CLI** (headless + JSON output)
* **Claude Code** (headless `-p/--print`, structured output options)
* **Codex** via official GitHub Action / CLI exec

All of these have non-interactive/headless affordances you can wire into CI:

* Kimi CLI **Print Mode** is explicitly for automation and can emit JSONL tool traces; it also implicitly enables YOLO auto-approval in that mode. ([Moonshot AI][2])
* Gemini CLI has a documented **Headless Mode** designed for scripting/CI, including JSON output. ([Google Gemini][3])
* Claude Code supports non-interactive execution with `-p/--print` and structured output controls. ([Claude Code][4])
* OpenAI provides a **Codex GitHub Action** that installs the CLI and runs `codex exec` in workflows. ([OpenAI Developers][5])

**But**: full agent CLIs introduce the exact permission / “YOLO mode” / “agent runs shell commands” risk you were worrying about. So I’d make Mode 3 **opt-in** (trusted repos only, or “deep review” label).

---

## “YOLO / dangerously skip permissions” in CI: don’t do it by default

In a GitHub runner, the agent has access to:

* the checked-out code
* workflow environment
* potentially build tooling
* and (critically) **secrets** needed to call model APIs

Even if the PR is trusted, a prompt injection inside the diff could try to make the agent do something dumb.

So the safe default is:

* **No shell tool** for the model (use bounded context loop instead)
* Or run CLIs in a **locked sandbox** (container, no secrets exposed except the provider key, no network except to the model endpoint, read-only mount for the repo if possible)

Also note:

* Kimi CLI supports explicit `--yolo` as a mode toggle, and its docs warn it skips confirmations. ([Moonshot AI][6])
* OpenCode has an explicit **permissions configuration** concept as well. ([OpenCode][7])

---

## Cost control: make Kimi the “workhorse” reviewer

If you want powerful + affordable as the baseline, your instinct to lean on **Kimi K2.5** is rational.

Moonshot’s official pricing page shows **cached input vs cache-miss input vs output** rates for kimi‑k2.5 (and other models). ([Moonshot AI][8])
That cached-input line is a big deal for repeated context across reviewers (repo summary, common docs).

Also: if you want “multiple providers,” you can:

* run Kimi via Moonshot directly
* run some reviewers via OpenRouter (different routing/prices)
* run one “premium” reviewer only on high-risk changes

OpenRouter’s model card lists its own Kimi K2.5 pricing (often different from Moonshot direct). ([OpenRouter][9])

**Practical policy that avoids bankruptcy:**

* 3–4 reviewers use Kimi K2.5 (or K2 Thinking variants)
* 1 “gold standard” reviewer (expensive) runs only when:

  * auth/security-sensitive files change
  * migrations touch production tables
  * dependency updates exceed a threshold
  * OR when an override is requested (“prove it wrong”)

---

## The override mechanism you want (blocking, but escapable with a paper trail)

You don’t want “admins can bypass checks” as the main mechanism (that exists via rulesets/bypass actors), because you want *intentional author work* + a recorded rationale. ([Stack Overflow][10])

### Recommended override design

* The only *required* check is **Council Verdict**
* Council Verdict passes only if:

  * all required reviewers approved **OR**
  * an override is present **for this exact HEAD SHA**

**Override command (comment)**
Example:

```
/council override sha=abc1234
Reason: Athena flags missing context; confirmed invariant in FooManager + upstream contract in docs/arch.md.
```

Rules:

* Must be authored by the **PR author** (configurable to “anyone with write” later)
* Must include a non-empty reason
* Must bind to **current HEAD SHA** to prevent “override once, merge forever”

What happens:

* Council Verdict becomes ✅ PASS
* The Council Verdict output includes:

  * who overrode
  * the reason
  * which reviewers were overridden
* Optional: the overridden reviewer check(s) can be set to `neutral`/`skipped` if you ever decide to require them too (GitHub treats those as acceptable for protected branches). ([GitHub Docs][1])

---

## Configuration spec: what I’d put in `.github/ai-council.yml`

Key ideas:

* reviewers are declarative
* each reviewer chooses:

  * model/provider
  * perspective prompt
  * context mode
  * override policy
  * budget/timeouts

Sketch:

```yaml
council:
  required_check_name: "Council Verdict"
  mode: parallel
  cancel_in_progress: true

override:
  allowed: true
  actor: pr_author         # pr_author | write_access | maintainers_only
  must_include_reason: true
  must_pin_sha: true

reviewers:
  - name: CERBERUS
    perspective: security
    engine: bounded_agent
    model: moonshot/kimi-k2.5
    override: maintainers_only

  - name: THEMIS
    perspective: standards-and-correctness
    engine: bounded_agent
    model: moonshot/kimi-k2.5
    override: pr_author

  - name: VULCAN
    perspective: implementation-and-tests
    engine: bounded_agent
    model: moonshot/kimi-k2.5
    override: pr_author

  - name: ATHENA
    perspective: architecture-and-maintainability
    engine: bounded_agent
    model: moonshot/kimi-k2.5
    override: pr_author

  - name: ARES
    perspective: performance-and-scalability
    engine: bounded_agent
    model: moonshot/kimi-k2.5
    override: pr_author
```

You can also support a **project “AI context” file** (AGENTS.md or similar) that each reviewer is instructed to read first. Kimi CLI even suggests generating an `AGENTS.md` to help the AI understand project structure/conventions. ([Moonshot AI][11])

---

## “Council member” naming: better than Athena/Vulcan/etc for reviewers

For a *review council* (not a sprite fleet), I’d pick names that scream “judge / gate / watchdog”:

**Mythic-legal**

* **THEMIS** = law/policy (standards, correctness discipline)
* **CERBERUS** = gatekeeper (security/secrets)
* **ARGUS** = many-eyed watcher (suspicious diffs, regressions)
* **DAEDALUS** = clever systems builder (architecture smell detector)
* **NEMESIS** = consequences (performance / cost / complexity blowback)

**Cold War contractor**

* **GAVEL** (policy, standards)
* **SENTINEL** (security)
* **WATCHTOWER** (architecture risk + cross-file coupling)
* **REDLINE** (performance + safety thresholds)
* **CLEARANCE** (dependency/license/compliance)

---

## Project names that fit this *and* feel “terrific”

You want: **unanimous**, **blocking gate**, **council**, **oversight**, **contractor vibe**.

Here are the best options I can think of, grouped by vibe:

### Contractor / program names (my strongest set)

* **PROJECT QUORUM**
* **PROJECT GAVEL**
* **PROJECT IRON GATE**
* **PROJECT CLEARANCE**
* **PROJECT OVERSIGHT**
* **PROJECT REDLINE**
* **PROJECT COUNTERSIGN**
* **PROJECT WATCHTOWER**
* **PROJECT SENTINEL**
* **PROJECT VETOBOARD**

### Clean, product-y, memorable OSS names

* **Unanimous**
* **MergeVeto**
* **QuorumCheck**
* **Gatekeeper**
* **CouncilCI**
* **VetoGate**
* **IronGate**
* **Redline Review**
* **The Gavel**
* **The Council**

### Myth + contractor hybrid (surprisingly good)

* **Themis Gate**
* **Cerberus Check**
* **Areopagus**
* **Aegis Council**
* **Argus Oversight**
* **Olympus Quorum**
* **Minos Protocol**
* **TribunalCI**
* **Pax Gate**
* **Aegis Redline**

If you want my top 3 that feel *brandable and serious*:

1. **PROJECT QUORUM**
2. **IRON GATE**
3. **PROJECT GAVEL**

---

## My “best bet” recommendation for your MVP

If you want something you can ship fast **without building a whole agent platform**:

1. Implement the council as a GitHub Action workflow:

   * matrix jobs = reviewer checks
   * each job posts/updates a PR comment

2. Start with **bounded context-request loop** (2 rounds max) so reviewers can “pull in” implicated files safely.

3. Use **Kimi K2.5** as default model/provider (cheap baseline), reserve premium models for optional deep review.

4. Add the override command early, but:

   * allow override for product/style/perf reviewers
   * require maintainer override for security reviewer (Cerberus)

If you tell me whether you prefer the naming tone **(Project QUORUM / IRON GATE / Project GAVEL)**, I’ll propose:

* a canonical council roster of 5 with roles
* the exact PR comment template (consistent + skimmable)
* and a concrete workflow YAML layout (setup → matrix reviewers → verdict) that supports overrides and comment upserts.

- [The Verge](https://www.theverge.com/news/873665/github-claude-codex-ai-agents?utm_source=chatgpt.com)
- [The Verge](https://www.theverge.com/news/692517/google-gemini-cli-ai-agent-dev-terminal?utm_source=chatgpt.com)
- [TechRadar](https://www.techradar.com/pro/google-gemini-and-github-are-teaming-up-for-ai-powered-coding?utm_source=chatgpt.com)
- [itpro.com](https://www.itpro.com/business/business-strategy/openais-codex-developer-agent-just-got-a-big-update?utm_source=chatgpt.com)

[1]: https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches?utm_source=chatgpt.com "About protected branches"
[2]: https://moonshotai.github.io/kimi-cli/en/customization/print-mode.html "Print Mode | Kimi Code CLI Docs"
[3]: https://google-gemini.github.io/gemini-cli/docs/cli/headless.html "Headless Mode | gemini-cli"
[4]: https://code.claude.com/docs/en/headless?utm_source=chatgpt.com "Run Claude Code programmatically - Claude Code Docs"
[5]: https://developers.openai.com/codex/github-action/?utm_source=chatgpt.com "Codex GitHub Action"
[6]: https://moonshotai.github.io/kimi-cli/en/guides/interaction.html?utm_source=chatgpt.com "Interaction and Input | Kimi Code CLI Docs"
[7]: https://opencode.ai/docs/permissions/?utm_source=chatgpt.com "Permissions"
[8]: https://platform.moonshot.ai/docs/pricing/chat?utm_source=chatgpt.com "Model Inference Pricing Explanation"
[9]: https://openrouter.ai/moonshotai/kimi-k2.5?utm_source=chatgpt.com "Kimi K2.5 - API, Providers, Stats"
[10]: https://stackoverflow.com/questions/71669640/bypass-required-status-checks-in-github?utm_source=chatgpt.com "Bypass required Status Checks in GitHub"
[11]: https://moonshotai.github.io/kimi-cli/en/guides/getting-started.html "Getting Started | Kimi Code CLI Docs"

