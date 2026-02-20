# Health Check Monitors

This module introduces a baseline agentic health-check runtime under `pkg/healthcheck`.

## What it contains

- `pkg/healthcheck/config.py` — validation and parsing for check configuration.
- `pkg/healthcheck/checker.py` — synchronous check execution and transition tracking.
- `pkg/healthcheck/alerters.py` — alert sink abstractions for webhook, PR comment, and GitHub-issue outputs.
- `tests/test_healthcheck.py` — unit tests for parsing, pass/fail checks, and transition alerts.

## Current stage

The monitoring engine is implemented as a reusable foundation. It does not yet include:

- automatic scheduler wiring (cron/Actions trigger loop), or
- automatic alert dispatch to external services.

That behavior should be added by a future action entrypoint that invokes `HealthMonitor` with the desired sinks.
