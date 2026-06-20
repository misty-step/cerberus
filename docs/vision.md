# Cerberus Vision

Status: active product north star.

## Audience

Cerberus is for operators who want a dependable AI code review agent they can
run from arbitrary review contexts: a local branch, a GitHub pull request, a
task-system diff, a hosted worker, or a future event plane.

## Job To Be Done

Given a change and whatever context is safely available, Cerberus should
produce a trustworthy review artifact and, when asked, project that artifact
into the operator's normal review surface without overstating evidence.

## Category

Cerberus is a Rust review runner and artifact contract. It is not a benchmark
lab, event plane, hosted multi-tenant service, or static reviewer swarm.

## Standards

- Context truth is non-negotiable: every artifact records what Cerberus could
  actually inspect.
- The stable seam is `ReviewRequest.v1 -> ReviewArtifact.v1`.
- Rust owns contracts, capability boundaries, execution receipts, validation,
  and rendering.
- Agent substrates own reviewer judgment and any runtime lane/subagent design.
- OpenCode is the default production-oriented substrate; OMP remains a local
  fallback behind the same harness contract.
- Verification must catch likely publication and execution failures before
  Cerberus becomes an automatic reviewer.

## Non-Goals

- No first-party model leaderboard in Cerberus.
- No hardcoded reviewer personas in Rust.
- No GitHub-only product boundary.
- No ambient credential inheritance.
- No direct provider orchestration unless a future ADR proves the substrate
  boundary cannot support the needed capability.

## Strategic Bets

1. A strict review artifact is more valuable than a clever reviewer transcript.
2. A single excellent master reviewer with dynamic substrate lanes beats a
   static reviewer roster embedded into product code.
3. A caller-neutral artifact plus small projection adapters will age better
   than a GitHub-native core.
4. Upstream labs such as Daedalus should evaluate models and harnesses;
   Cerberus should emit enough receipts for those labs to score real runs.

## Six To Twelve Month Target

Cerberus is the default code review agent for Misty Step repositories. A
single command or thin caller can review a PR, run inside an isolated review
workspace, produce a validated artifact, publish GitHub checks/reviews with
idempotent markers, and preserve receipts for later evaluation. Operators can
see what context was used, what was skipped, what cost/time was incurred, and
why each comment exists.
