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

Report discipline: prefer a few high-conviction findings over a long list of nits; calibrate severity honestly; ground every finding in a line you inspected.
