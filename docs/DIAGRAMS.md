# Diagrams

## OSS GitHub Action Flow

```mermaid
flowchart TD
  PR[GitHub PR event\nopened|synchronize|reopened] --> MATRIX[Matrix job\nuses: cerberus/matrix@v2\noutputs: strategy.matrix JSON]

  MATRIX --> REVIEW_FANOUT[Review job\nstrategy.matrix = JSON\nfail-fast: false]

  REVIEW_FANOUT -->|N parallel jobs| REVIEW[action.yml\nuses: cerberus@v2\n(single perspective)]

  REVIEW --> CTX[Fetch PR diff + context\n(gh pr diff/view)]
  CTX --> LLM[Run reviewer\n(opencode run --agent <perspective>)]
  LLM --> PARSE[Parse reviewer output -> verdict.json\nscripts/parse-review.py]

  PARSE -->|uploads| ART[(Artifacts\ncerberus-verdict-<perspective>)]
  PARSE -->|optional| RCOMMENT[PR issue comment\nmarker: cerberus:<perspective>]

  ART --> VERDICT[Verdict job\nuses: cerberus/verdict@v2]

  OVERRIDE[/PR comment command\n/cerberus override sha=<sha>\n(reason required)/] --> VERDICT

  VERDICT --> AGG[Aggregate verdicts + apply overrides\nscripts/aggregate-verdict.py]
  AGG --> CCOMMENT[PR issue comment\nmarker: cerberus:verdict]
  AGG --> INLINE[PR review\ninline comments (best-effort, capped)]
  AGG --> CHECK[Final job conclusion\n(fail-on-verdict gates merge)]
```

## Triage Flow (Loop Guards)

```mermaid
stateDiagram-v2
  [*] --> Disabled: TRIAGE_MODE=off\nor CERBERUS_TRIAGE=off
  [*] --> SelectTargets: TRIAGE_MODE=diagnose|fix

  SelectTargets --> EvaluatePR: pull_request (automatic)\n1 target
  SelectTargets --> EvaluatePR: issue_comment (manual)\ncommand starts with /cerberus triage
  SelectTargets --> EvaluatePR: schedule|workflow_dispatch (scheduled)\nscan open PRs

  EvaluatePR --> Skipped: latest trusted verdict comment missing
  EvaluatePR --> Skipped: Cerberus verdict != FAIL
  EvaluatePR --> Skipped: attempts_for_sha >= max_attempts
  EvaluatePR --> Skipped: head commit message contains [triage]
  EvaluatePR --> Skipped: scheduled && not stale_enough\n(now - verdict.updated_at < stale_hours)

  EvaluatePR --> Diagnosed: mode=diagnose
  EvaluatePR --> Diagnosed: mode=fix but blocked\n(trigger != automatic | fork | no .git)

  EvaluatePR --> Fixing: mode=fix && trigger=automatic\n&& same-repo && has .git

  Fixing --> Fixed: fix-command ok + changes\n+ push ok
  Fixing --> NoChanges: fix-command ok\n+ no file changes
  Fixing --> FixFailed: fix-command failed\nor push failed

  Diagnosed --> Commented
  Fixed --> Commented
  NoChanges --> Commented
  FixFailed --> Commented

  Commented --> [*]: post PR comment\nmarker: cerberus:triage sha=<short> run=<id>

  note right of EvaluatePR
    "trusted" = CERBERUS_BOT_LOGIN (default github-actions[bot])
    verdict marker = cerberus:verdict
    attempt count = trusted comments containing "cerberus:triage sha=<sha-prefix>"
  end note
```

## Cerberus Cloud (Proposed) GitHub App Flow

```mermaid
sequenceDiagram
  participant GH as GitHub
  participant WH as Cerberus Cloud (Webhook Ingest)
  participant DB as Storage (runs, overrides, results)
  participant Q as Queue
  participant W as Reviewer Workers
  participant AGG as Aggregator/Reporter

  GH->>WH: Webhook: pull_request opened|synchronize|reopened
  WH->>DB: Upsert ReviewRun{repo, pr#, head_sha}\n(idempotent by delivery_id + head_sha)
  WH->>Q: Enqueue ReviewRun(head_sha)

  Q->>AGG: Start run(head_sha)
  AGG->>Q: Fan-out reviewer tasks\n(APOLLO..CASSANDRA)

  par Each reviewer
    Q->>W: Task(reviewer, head_sha)
    W->>GH: Fetch diff/context via GitHub API (read-only)
    W->>W: LLM review + JSON verdict
    W->>DB: Store verdict(reviewer, head_sha)
  end

  AGG->>DB: Read all verdicts + overrides
  AGG->>AGG: Compute aggregated verdict
  AGG->>GH: Create/Update Check Run on head_sha\nsummary + annotations
  AGG->>GH: Optional PR issue comment\nmarker: cerberus:verdict

  GH->>WH: Webhook: issue_comment created\n(/cerberus override sha=...)
  WH->>DB: Persist override (only if sha matches HEAD)
  WH->>Q: Enqueue Re-aggregate(head_sha)
  Q->>AGG: Update Check Run / verdict comment
```

