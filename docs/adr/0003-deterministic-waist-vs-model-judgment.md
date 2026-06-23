# ADR 0003: The deterministic waist vs. model judgment

Date: 2026-06-23

Status: Accepted

## Context

Cerberus risks deterministic-heuristic overreach — encoding hand-crafted rules to
enforce the *quality* of a review. That betrays Sutton's bitter lesson (general
methods that scale with computation beat built-in human knowledge) and invites
Goodhart / reward-hacking the moment a "verifier" is a hand-crafted proxy for
meaning. A backlog ticket (007) proposed a Rust gate that "rejects findings whose
evidence doesn't resolve" — conflating two very different properties.

Grounded by research (2026-06-23): Sutton, *The Bitter Lesson* (2019); OpenAI
Structured Outputs (~100% schema compliance vs <40% for prose, 2024); reward-hacking
hand-crafted proxies (Gao et al., ICML 2023; Krakovna/DeepMind, 2020 — a summarizer
gaming ROUGE); LLM-as-judge for open-ended quality (MT-Bench/Zheng 2023; G-Eval
2023); and Wallat et al., "Correctness is not Faithfulness in RAG Attributions"
(2024), which names the split below.

## Decision

Deterministic Rust owns the **narrow waist — and only it.** The test for any
proposed check: **can a non-AI oracle decide pass/fail with certainty?**

- **Yes → deterministic.** Schema/contract well-formedness; referential integrity;
  request↔artifact digest; declared-tier ≤ granted-tier; safety/isolation/
  no-secret-leak/bounded-output/no-orphans; idempotent posting; posting-correctness
  (an inline anchor maps to a real changed line); and **citation/anchor resolution**
  (the cited path/line exists and, where a `hunk_digest`/`excerpt` is provided,
  matches the file bytes). These hold regardless of model quality and can't be gamed.
- **No → model + evals.** Semantic *faithfulness* (is a finding correct,
  non-hallucinated, useful?), severity calibration, what to explore, what to flag.
  A deterministic verifier here is a proxy for meaning → Goodhart. Improve it by
  **harness engineering** (prompt / context / tools / model) and **measure** it with
  evals (LLM-as-judge vs a human-labeled baseline, reported with a confidence
  interval).

Corollary: "configure the agent and let it do its thing" applies to *judgment*. It
does **not** apply to safety, contracts, or side-effects — those stay deterministic.

## Consequences

- `validation.rs` stays as-is: it is already pure contract / safety / posting, with
  zero quality heuristics and `category` left agent-free-form. The feared "heuristic
  spaghetti" was a *proposal*, not the code.
- **007 is narrowed** to the legitimate half — citation/anchor *resolution* (a real
  oracle). The faithfulness half is deleted and replaced by an eval+harness loop
  (**015**), the actual trust moat VISION names ("trust earned by low false-confident
  rate, *measured*").
- Artifact emission moves from a hand-specified prose JSON contract to native
  **structured output** (**016**), deleting the defensive marker/XML/raw parsing that
  exists only because the prose contract is unreliable.
- Every new ticket is tested against this line: "enforce X in Rust" must name its
  oracle, or it becomes an eval.

## Alternatives Considered

- *Enforce groundedness/faithfulness in Rust* (the original 007): rejected — there is
  no oracle for "faithful," so it degrades into gameable heuristics.
- *Prompt-only, no deterministic checks*: rejected — drops the cheap, un-gameable
  resolution wins and abandons the safety/contract waist.
