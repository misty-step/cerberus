Review vocabulary — what to hunt, beyond surface correctness. Severity discipline still governs: correctness, security, and behavior regressions outrank everything below; the structure and smell vocabulary is mostly minor/major judgement calls.

Plausible-but-wrong (the failure mode of model-written code):
- Stub or specification-shaped code that passes tests but does not do the work.
- Wrong complexity hidden behind a clean interface (e.g. O(n^2) where O(n) is expected).
- Tests that never invoke the changed entrypoint (adjacent green lanes).
- Missing invariant checks that only bite at scale or under concurrency.
- Swallowed errors, silent magic fallbacks, internal mocks standing in for real seams.
- Unnecessary abstraction — wrappers, modes, layers that do not earn their keep.

Fowler smells (Refactoring Ch.3 — every smell is a judgement call, never an automatic FAIL; a documented repo standard overrides any of these). The name carries its definition; tie each to the specific line you inspected:
- Mysterious Name — a name needs the body read to understand the call site.
- Duplicated Code — the diff repeats structure that already exists, or repeats itself.
- Feature Envy — a method touches another type's data more than its own.
- Data Clumps — the same three-plus fields or params travel together; they want one object.
- Primitive Obsession — a string/int/map stands in for a domain concept that wants its own type.
- Repeated Switches — the same type-switch appears in two-plus places; a new case edits all of them.
- Shotgun Surgery — one logical change forced scattered edits across many files or functions.
- Divergent Change — one module is edited for unrelated reasons; it has too many responsibilities.
- Speculative Generality — an abstraction, hook, or param with no current caller.
- Message Chains — the caller navigates a.getB().getC().getD() structure it should not know.
- Middle Man — a class or method that mostly delegates; a hop without value.
- Refused Bequest — an impl ignores or overrides most of what it inherits or the interface it claims.

Structural bar (be ambitious, not nitpicky):
- A diff that pushes a file past roughly 1000 lines is a decomposition smell unless there is a strong reason.
- New ad-hoc conditionals bolted onto unrelated flows are a design problem, not a style nit.
- Prefer the behavior-preserving "code judo" reframe that deletes whole branches over a refactor that merely rearranges the same complexity.

Model-boundary judgment (mandatory dimension — heuristic-where-a-model-belongs-and-model-where-deterministic-code-belongs): every review asks both directions, not just one:
- Did this change replace judgment, semantic classification, realtime, speech, vision, agentic capability, or other model-native product behavior with a brittle keyword heuristic, regex, or fixed lookup table that will silently misfire outside the cases the author tested?
- Did this change add a model call where deterministic code should own the behavior instead — scoring, policy, persistence, approval, sandboxing, security enforcement, or anything else an eval or an oracle-checkable test can verify directly?
- This is architectural judgment about where a product boundary sits, not a rule engine: do not fail a review solely because a model call exists near policy code, or because a heuristic exists near natural-language input — ground the finding in the specific behavior the diff actually changed.

Stack-aware review: when the request is part of a stacked PR chain, review the
current PR as a slice, not as the whole feature.
- Verify the PR base and stack order before judging merge readiness. The bottom
  PR should target the default branch; upper PRs should target the previous
  stack branch until lower slices merge.
- Distinguish defects introduced by this PR from defects already present in lower stack PRs.
  Findings should land on the first PR that introduced the problem.
- Treat missing lower-stack context as residual risk, not as proof of a bug in
  the upper PR.
- Call out partitioning mistakes explicitly: "belongs in lower PR",
  "upper PR depends on an unmerged behavior", or "base branch appears wrong".
- For merge-readiness comments, require bottom-up merge order and a final
  default-branch sync check after the last PR lands.

Report discipline: prefer a few high-conviction findings over a long list of nits; calibrate severity honestly; ground every finding in a line you inspected.
