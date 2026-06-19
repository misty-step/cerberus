# ADR 0001: Unarchive Cerberus for Active Delivery

Date: 2026-06-19

Status: Accepted

## Context

Cerberus was previously archived and treated as design donor material for the
automated review stack. That was correct while the project had no active
implementation plan and while adjacent systems owned eventing, evaluation, and
production review concerns.

The restart changed the repo's status. Cerberus now has an accepted MVP shape:
a Rust review runner with one predefined master reviewer, context-adaptive
request and artifact contracts, OpenCode as the preferred production substrate,
OMP as a local fallback, fixture verification, and caller-neutral artifacts.
The implementation is locally verified, but an archived GitHub repository is
read-only and blocks pushing a branch, opening review, and treating the repo as
merge-ready.

## Decision

Unarchive `misty-step/cerberus` and treat it as an active delivery repository
again.

Unarchiving is not a statement that every archived review-system experiment
should be revived. It is justified here because the current work has:

- a fresh specification in `spec.md`;
- a working Rust implementation;
- a repository-local verification command, `./scripts/verify.sh`;
- a clean branch intended for review and merge;
- explicit stack boundaries with Daedalus and Bitterblossom.

## Consequences

Cerberus can now accept pushed branches, pull requests, CI wiring, issues, and
normal repository maintenance. Future delivery work should use the canonical
GitHub repo as the writable source of truth instead of treating it as archived
prior art.

The cost is that Cerberus re-enters the active surface area of the review
stack. To keep that surface disciplined, Cerberus should stay focused on the
review runner contract and avoid absorbing evaluation laboratory,
event-plane, or GitHub-posting responsibilities that belong to adjacent
systems.

## Alternatives Considered

Leave the repo archived and keep local-only commits.

This preserves the old donor-material stance, but it makes the restarted
implementation impossible to publish, review, or merge in the canonical repo.

Create a new repository.

This avoids changing archive state, but it splits history and obscures the
intentional restart. The current repo name and history are useful context as
long as the new implementation keeps its surface narrow.
