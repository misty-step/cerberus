# Cerberus Eval System

This directory contains the Promptfoo-based evaluation system for measuring Cerberus reviewer quality.

## Structure

```text
evals/
├── promptfooconfig.yaml    # Main eval configuration
├── datasets/               # Test case datasets (future)
├── prompts/                # Prompt templates (future)
├── results/               # Eval results (generated)
│   ├── latest.json        # Latest results
│   ├── baseline.json     # Baseline for regression detection
│   ├── smoke-output.txt  # Smoke eval output
│   └── full-output.txt  # Full eval output
└── README.md             # This file

.github/workflows/
├── smoke-eval.yml          # PR-triggered smoke eval
└── full-eval.yml           # Nightly full eval
```

## Running Evals Locally

### Prerequisites

```bash
npm install -g promptfoo@0.120.24
export OPENROUTER_API_KEY=your-key
```

### Smoke Eval (fast, ~2 min)

```bash
promptfoo eval --config evals/promptfooconfig.yaml --no-cache --max-concurrency 3
```

### Full Eval (complete, ~15 min)

```bash
promptfoo eval --config evals/promptfooconfig.yaml --no-cache --max-concurrency 5
```

## Test Cases

The eval includes 31 test cases across 6 perspectives:

| Perspective | Count | Description |
|------------|-------|-------------|
| security   | 5     | SQL injection, XSS, secrets, etc. |
| correctness| 5     | Bugs, null pointers, logic errors |
| performance| 5     | N+1 queries, memory leaks, I/O |
| architecture| 5    | Coupling, interfaces, layering |
| maintainability| 5 | Duplication, naming, docs |
| testing    | 5     | Coverage, mocks, assertions |

## CI Integration

### Smoke Eval
- **Trigger:** PR changes to `evals/**`, `templates/**`, `.opencode/agents/**`
- **Threshold:** 80% pass rate
- **Output:** PR comment with summary

### Full Eval
- **Trigger:** Nightly (2 AM UTC) or manual `workflow_dispatch`
- **Threshold:** 85% pass rate
- **Output:** Artifacts only, regression alerts if >5% drop from baseline

## Adding Test Cases

Edit `evals/promptfooconfig.yaml` and add entries to the `tests` array:

```yaml
- description: "Your test name"
  vars:
    pr_title: "..."
    # ... other vars
  assert:
    - type: javascript
      value: "output.verdict === 'FAIL'"
```

### Assertion Types

| Type | Use Case |
|------|----------|
| `javascript` | Structured checks: verdict, findings, severity |
| `llm-rubric` | Qualitative: "identifies root cause" |
| `similar` | Consistency across runs |
| `not-contains` | False positive guard |
| `is-json` | Schema compliance |

## Metrics

- **Verdict Accuracy:** Does the reviewer produce the correct verdict?
- **Finding Relevance:** Do findings reference real issues?
- **False Positive Rate:** Does clean code pass without findings?
- **Consistency:** Same input → same verdict across runs
- **Parse Compliance:** Output matches required JSON schema

## References

- [Promptfoo Docs](https://promptfoo.dev/docs/intro/)
- [LLM Evaluation Best Practices](https://promptfoo.dev/docs/guides/evaluate-llm/)
