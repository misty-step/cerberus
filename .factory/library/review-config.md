# Review Configuration

Guidance for the merged reviewer configuration and planner-facing bench model.

**What belongs here:** reviewer bench structure, override expectations, planner/config interactions.
**What does NOT belong here:** live secrets or environment-variable values.

---

- Mission requirement: usable reviewer configurability now for models, prompts, providers, and reviewer bench composition
- Favor one merged config model over multiple parallel config files
- Keep reviewer identity explicit and stable so overrides can target reviewers deterministically
- Planner must consume the active bench produced by the merged config; removed or disabled reviewers must not remain selectable
- Prefer built-in defaults plus explicit override surfaces that can work with a packaged CLI artifact
- Keep prompt/template identity auditable in validation artifacts (path and/or digest), not just human-friendly labels
