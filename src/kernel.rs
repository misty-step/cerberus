use std::path::PathBuf;
use std::time::Duration;

use anyhow::{Context, Result};

use crate::container::{run_container_substrate, ContainerOpencodeSubstrateConfig};
use crate::harness::{
    run_command_substrate, run_fixture_substrate, CommandSubstrateConfig, ExecutionPlan,
    FixtureSubstrateConfig, HarnessRun, OmpSubstrateConfig, OpenCodeSubstrateConfig,
};
use crate::orchestration::{build_reviewer_plan, ReviewerPlanReceipt};
use crate::schema::{ReviewArtifact, ReviewRequest, ReviewTelemetry};
use crate::workflow_lock::{acquire_workflow_lock, default_workflow_lock_path};

#[derive(Debug, Clone)]
pub struct ReviewKernel {
    pub substrate: ReviewSubstrate,
}

#[derive(Debug, Clone)]
pub enum ReviewSubstrate {
    Fixture(FixtureSubstrateConfig),
    Opencode(OpenCodeSubstrateConfig),
    Omp(OmpSubstrateConfig),
    ContainerOpencode(ContainerOpencodeSubstrateConfig),
}

#[derive(Debug, Clone)]
pub struct RunPolicy {
    pub timeout: Duration,
    pub failure_transcript: Option<PathBuf>,
}

#[derive(Debug, Clone)]
pub struct ReviewRun {
    pub artifact: ReviewArtifact,
    pub transcript: String,
    pub execution_plan: ExecutionPlan,
    pub reviewer_plan: ReviewerPlanReceipt,
    pub telemetry: ReviewTelemetry,
}

impl ReviewRun {
    /// A `ReviewRun` is a completed `HarnessRun` plus the reviewer plan,
    /// which can only be built after the harness run finishes (it summarizes
    /// the run's own execution plan and telemetry). Named here so that
    /// relationship is explicit instead of an anonymous field-copy literal.
    fn from_harness(run: HarnessRun, reviewer_plan: ReviewerPlanReceipt) -> Self {
        Self {
            artifact: run.artifact,
            transcript: run.transcript,
            execution_plan: run.execution_plan,
            reviewer_plan,
            telemetry: run.telemetry,
        }
    }
}

impl ReviewSubstrate {
    pub fn fixture(output: PathBuf) -> Self {
        Self::Fixture(FixtureSubstrateConfig { output })
    }
}

impl ReviewKernel {
    pub fn new(substrate: ReviewSubstrate) -> Self {
        Self { substrate }
    }

    /// Every caller-neutral entrypoint (`review`/`review-diff`/`review-pr`
    /// in `main.rs`, and the MCP server in `mcp.rs`) funnels through this
    /// one method, so this is the single place a global review-workflow
    /// semaphore needs to be acquired to cover all of them. See
    /// `crate::workflow_lock` for why the lock is host-wide (not
    /// per-process) and non-blocking.
    pub fn review(&self, request: &ReviewRequest, run_policy: &RunPolicy) -> Result<ReviewRun> {
        let _workflow_lock = acquire_workflow_lock(&default_workflow_lock_path())
            .context("acquire global review workflow lock")?;
        let run = match &self.substrate {
            ReviewSubstrate::Fixture(config) => {
                run_fixture_substrate(request, run_policy.timeout, config)?
            }
            ReviewSubstrate::Opencode(config) => run_command_substrate(
                CommandSubstrateConfig::Opencode(config),
                request,
                run_policy.timeout,
                run_policy.failure_transcript.as_deref(),
            )?,
            ReviewSubstrate::Omp(config) => run_command_substrate(
                CommandSubstrateConfig::Omp(config),
                request,
                run_policy.timeout,
                run_policy.failure_transcript.as_deref(),
            )?,
            ReviewSubstrate::ContainerOpencode(config) => {
                run_container_substrate(request, run_policy.timeout, config)?
            }
        };
        let reviewer_plan = build_reviewer_plan(request, &run.execution_plan, &run.telemetry)?;
        Ok(ReviewRun::from_harness(run, reviewer_plan))
    }
}
