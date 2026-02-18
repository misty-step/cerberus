# Error Tracking & Logging

This module provides a local, dependency-light error tracking pipeline used by
Cerberus for v2.0 observability work.

## What it provides

- Source configuration for reading a log file path, choosing format, and matching
  error patterns.
- Plain-text and JSON parsers that emit normalized `ParsedError` events.
- Grouping by normalized signature (stack text preferred, message fallback).
- In-memory counters with:
  - total count
  - first/last seen timestamp
  - per-source dedupe
  - rolling trend buckets
- Alert events when:
  - a new error group appears
  - a group's error rate spikes against the previous window

## Modules

- `pkg/errortracking/config.py` — source + runtime validation and defaults.
- `pkg/errortracking/parser.py` — parse logs into `ParsedError` events.
- `pkg/errortracking/grouper.py` — group events, detect spikes, and build dashboard data.

## Public API

### Parsing

```
config = ErrorSourceConfig.from_dict({...})
errors = LogParser(config).parse()
```

### Grouping

```
grouper = ErrorGrouper(spike_window_seconds=3600, spike_multiplier=2.5, spike_min_count=5)
groups, alerts = grouper.ingest(errors)
dashboard = grouper.build_dashboard()
```

`groups` contain aggregate counters and raw trend samples. `alerts` contain
`new_error_type` or `error_rate_spike` events.

## Current scope

This is a local, in-memory implementation. It does not write to external storage
or fire network alerts by default. That integration is intended for a follow-up
story.
