# PR Walkthrough: Issue #448

## Goal

Delete dead Elixir worker code, remove the shallow `Cerberus.ReviewSupervisor` wrapper module, and keep the existing runtime supervisor name by inlining the child spec in `Cerberus.Application`.

## Before

- `Cerberus.BB.Worker` and `Conductor.Worker` existed only to support an abandoned BB integration path.
- `Cerberus.ReviewSupervisor` wrapped `DynamicSupervisor` without adding behavior, policy, or invariants.
- `test/worker_test.exs` spent coverage on the dead stub instead of a real runtime contract.
- The application supervision tree asserted the wrapper module itself rather than the actual named dynamic supervisor process.

## After

- The dead BB worker module, its behavior, and the dead worker test are gone.
- `Cerberus.Application` now builds the named `DynamicSupervisor` child spec directly and preserves the stable child ID.
- `test/application_test.exs` now verifies the registered `Cerberus.ReviewSupervisor` process and its empty child counts instead of the deleted wrapper module.
- The runtime name `Cerberus.ReviewSupervisor` is preserved for engine, pipeline, and reviewer code that starts reviewer processes under that supervisor.

## Verification

- `cd cerberus-elixir && grep -R "BB.Worker\|Conductor.Worker" lib/ test/`
  - Outcome: no matches
- `cd cerberus-elixir && mix compile --warnings-as-errors`
  - Outcome: passed
- `cd cerberus-elixir && mix test`
  - Outcome: `330 tests, 0 failures`
- `cd cerberus-elixir && grep -R "ReviewSupervisor" lib/ test/`
  - Outcome: the deleted wrapper module is gone; remaining hits are the inlined child spec, preserved runtime references, and the updated application test

## Persistent Check

`cd cerberus-elixir && mix test && mix compile --warnings-as-errors`

## Residual Risk

- The issue's literal `grep -r "ReviewSupervisor" lib/` acceptance criterion conflicts with its own boundary to preserve the runtime name in pipeline code. This branch removes the wrapper module and keeps only the references required to use the named supervisor.
