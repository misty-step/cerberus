# Cerberus Terminology

Cerberus needs a small, stable language. The goal is not to invent more labels; it is to make review, triage, and documentation talk about the same objects.

## Core Rule

A **finding** is a first-class reviewer claim.

It is not "verified" or "unverified" as a separate category. It may carry supporting attributes such as:

- `evidence`: exact quoted code or artifact excerpt
- `citation`: file/line reference, linked issue, or PR context
- `scope`: whether the claim is in the diff or a defaults-change path
- `severity`: how serious the problem is
- `confidence`: reviewer-level confidence in the review output

If a reviewer cannot support a finding with concrete repository evidence, the reviewer should omit the finding instead of inventing a weaker placeholder category.

Cerberus does not preserve deprecated finding-marker aliases as compatibility shims. Unsupported finding fields or deprecated title prefixes should fail validation instead of being silently translated.

## Nouns

| Term | Definition |
|------|------------|
| Review | One Cerberus run against a PR or branch diff. |
| Reviewer | One specialized agent that inspects the change from a single perspective. |
| Perspective | The analytical lens a reviewer owns, such as correctness, security, or testing. |
| Bench | The full set of Cerberus reviewers available to run. |
| Panel | The subset of reviewers selected for a specific review. |
| Wave | One stage of reviewer execution and escalation. |
| Finding | A standalone issue claim emitted by a reviewer. |
| Evidence | Verbatim quoted code or artifact text that supports a finding. |
| Citation | The exact location or external reference used to trace a finding. |
| Verdict | The outcome of a review or aggregate review: `PASS`, `WARN`, `FAIL`, or `SKIP`. |
| Aggregate verdict | The merged result across all reviewers in the panel. |
| SKIP | A reviewer produced no usable review result because the review did not complete cleanly. |
| Override | An authorized maintainer action that suppresses a blocking verdict for a specific SHA. |
| Triage | The follow-on diagnosis or fix loop for Cerberus findings or failures. |
| Walkthrough | A durable artifact that explains what changed and why the lane should merge. |
| Prompt contract | The instructions that define what a reviewer must inspect, cite, and output. |
| Review artifact | Structured output from a reviewer or aggregate step, including verdict JSON and comments. |

## Verbs

| Verb | Meaning in Cerberus |
|------|---------------------|
| Review | Inspect a diff from a specific perspective. |
| Emit | Produce a finding or verdict artifact. |
| Cite | Point to the exact file, line, or artifact supporting a claim. |
| Aggregate | Combine reviewer outputs into one verdict. |
| Gate | Use verdict policy to decide whether escalation or merge should stop. |
| Escalate | Advance from one wave to the next. |
| Skip | Stop a reviewer lane without a usable result. |
| Override | Authorize a blocking verdict exception for one commit. |
| Triage | Diagnose or remediate a failure or finding. |
| Remediate | Change code, config, or prompts to remove the root cause of a finding. |
| Anchor | Attach a finding to the right diff line or PR surface. |

## Distinctions That Matter

### Finding vs Verdict

- A **finding** is one issue claim.
- A **verdict** is the outcome of the full review or reviewer run.

### Evidence vs Citation

- **Evidence** is the quoted material itself.
- **Citation** is where that material came from.

### SKIP vs PASS

- `PASS` means the reviewer completed and found no actionable issues.
- `SKIP` means the reviewer did not complete a usable review.

### Reviewer Confidence vs Finding Support

- **Confidence** is a review-level signal about the quality of the review output.
- **Support** comes from evidence and citations attached to each finding.

Do not collapse these into "verified vs unverified finding." They describe different things.

## Terms to Avoid

- `verified finding`
- `unverified finding`
- `speculative finding`

Use this instead:

- `finding with evidence`
- `finding missing evidence`
- `finding citing unchanged defaults-change code`
- `suggestion not yet traced through the codebase`

## Writing Guidance

When describing Cerberus behavior:

1. Name the object first: review, reviewer, finding, verdict, skip, override.
2. Name the support second: evidence, citation, scope, confidence.
3. Name the action last: emit, aggregate, gate, triage, remediate.

Example:

- Good: "The reviewer emitted one major finding with exact evidence from `scripts/run-reviewer.py:84`."
- Bad: "Cerberus produced an unverified warning-ish thing."
