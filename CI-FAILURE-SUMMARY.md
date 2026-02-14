# CI Failure Summary

## Failing check
- **Workflow:** `Cerberus Council`
- **Run:** `22026142556`
- **Job:** `Council Verdict`
- **Step:** `Run /./verdict`
- **Exit code:** `1`

## Error summary (exact)
```
aggregate-verdict: override 1/1 from 'phrazzld': skipped (invalid or SHA mismatch)
Council Verdict: FAIL
Reviewers:
- ATHENA (architecture): PASS
- APOLLO (correctness): PASS
- ARTEMIS (maintainability): FAIL
- VULCAN (performance): WARN
- SENTINEL (security): PASS
- CASSANDRA (testing): FAIL
##[error]Council Verdict: FAIL
```

## Notes
- Smoke eval is green: `Eval - Smoke` run `22026142560` passed with **87%** (27/31).
- Council is red because 2 reviewers failed (ARTEMIS + CASSANDRA), so verdict action intentionally fails when `fail-on-verdict: true`.
