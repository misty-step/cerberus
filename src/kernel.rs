use std::path::PathBuf;
use std::time::Duration;

use anyhow::Result;

use crate::container::{run_container_substrate, ContainerOpencodeSubstrateConfig};
use crate::harness::{
    run_command_substrate, run_fixture_substrate, CommandSubstrateConfig, ExecutionPlan,
    FixtureSubstrateConfig, OmpSubstrateConfig, OpenCodeSubstrateConfig,
};
use crate::orchestration::{build_reviewer_plan, ReviewerPlanReceipt};
use crate::schema::{ReviewArtifact, ReviewRequest, ReviewTelemetry};

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
    pub cwd: PathBuf,
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

impl ReviewSubstrate {
    pub fn fixture(output: PathBuf) -> Self {
        Self::Fixture(FixtureSubstrateConfig { output })
    }
}

impl ReviewKernel {
    pub fn new(substrate: ReviewSubstrate) -> Self {
        Self { substrate }
    }

    pub fn review(&self, request: &ReviewRequest, run_policy: &RunPolicy) -> Result<ReviewRun> {
        let run = match &self.substrate {
            ReviewSubstrate::Fixture(config) => {
                run_fixture_substrate(request, &run_policy.cwd, run_policy.timeout, config)?
            }
            ReviewSubstrate::Opencode(config) => run_command_substrate(
                CommandSubstrateConfig::Opencode(config),
                request,
                &run_policy.cwd,
                run_policy.timeout,
                run_policy.failure_transcript.as_deref(),
            )?,
            ReviewSubstrate::Omp(config) => run_command_substrate(
                CommandSubstrateConfig::Omp(config),
                request,
                &run_policy.cwd,
                run_policy.timeout,
                run_policy.failure_transcript.as_deref(),
            )?,
            ReviewSubstrate::ContainerOpencode(config) => {
                run_container_substrate(request, run_policy.timeout, config)?
            }
        };
        let reviewer_plan = build_reviewer_plan(request, &run.execution_plan, &run.telemetry)?;
        Ok(ReviewRun {
            artifact: run.artifact,
            transcript: run.transcript,
            execution_plan: run.execution_plan,
            reviewer_plan,
            telemetry: run.telemetry,
        })
    }
}
