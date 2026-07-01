//! Minimal Model Context Protocol server for Cerberus.
//!
//! Transport is stdio with one JSON-RPC 2.0 message per line, matching the
//! simple local MCP servers used elsewhere in the fleet. stdout is the protocol
//! channel; diagnostics go to stderr.

use std::fs;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::kernel::{ReviewKernel, ReviewSubstrate, RunPolicy};
use crate::request::{build_git_range_request, GitRangeRequestOptions, RequestOptions};
use crate::schema::{RuntimeTarget, Verdict};
use crate::{
    render_markdown, validate_artifact_for_request, validate_request, FixtureSubstrateConfig,
    OmpSubstrateConfig, OpenCodeSubstrateConfig, ReviewArtifact, ReviewRequest,
};

const PROTOCOL_VERSION: &str = "2025-11-25";

pub fn run_stdio() -> Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();

    for line in stdin.lock().lines() {
        let line = line.context("read MCP stdin")?;
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let message: Value = match serde_json::from_str(line) {
            Ok(message) => message,
            Err(err) => {
                eprintln!("mcp: invalid JSON: {err}");
                continue;
            }
        };

        let id = message.get("id").cloned();
        let method = message
            .get("method")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let result = dispatch(method, &message);
        let Some(id) = id else { continue };

        let response = match result {
            Ok(value) => json!({ "jsonrpc": "2.0", "id": id, "result": value }),
            Err(err) => json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": { "code": -32603, "message": err.to_string() }
            }),
        };
        writeln!(stdout, "{}", serde_json::to_string(&response)?)?;
        stdout.flush()?;
    }

    Ok(())
}

fn dispatch(method: &str, message: &Value) -> Result<Value> {
    match method {
        "initialize" => Ok(json!({
            "protocolVersion": message["params"]["protocolVersion"]
                .as_str()
                .unwrap_or(PROTOCOL_VERSION),
            "serverInfo": {
                "name": "cerberus",
                "version": env!("CARGO_PKG_VERSION")
            },
            "capabilities": { "tools": { "listChanged": false } }
        })),
        "tools/list" => Ok(json!({ "tools": tool_defs() })),
        "tools/call" => call_tool(&message["params"]),
        "ping" => Ok(json!({})),
        other => Err(anyhow!("method not found: {other}")),
    }
}

fn tool_defs() -> Value {
    json!([
        {
            "name": "review_git_range",
            "description": "Review a committed local git range with Cerberus and return the rendered review plus verdict metadata. Use when an agent needs a branchable code review artifact without GitHub posting.",
            "inputSchema": {
                "type": "object",
                "required": ["base"],
                "properties": {
                    "repo_path": { "type": "string", "default": "." },
                    "base": { "type": "string", "description": "Base ref for git diff base...head." },
                    "head": { "type": "string", "default": "HEAD" },
                    "harness": { "type": "string", "enum": ["opencode", "omp", "fixture"], "default": "opencode" },
                    "fixture_output": { "type": "string", "description": "Fixture artifact template path; required when harness=fixture." },
                    "model": { "type": "string" },
                    "allow_env": { "type": "array", "items": { "type": "string" } },
                    "timeout_seconds": { "type": "integer", "minimum": 1, "default": 120 },
                    "fail_on": { "type": "string", "enum": ["none", "warn", "fail"], "default": "none" },
                    "json": { "type": "boolean", "description": "Return artifact JSON text instead of rendered Markdown." }
                }
            }
        },
        {
            "name": "render_review_artifact",
            "description": "Render a saved ReviewArtifact.v1 JSON file to Cerberus Markdown. Use when a caller already has an artifact and needs human-readable output.",
            "inputSchema": {
                "type": "object",
                "required": ["artifact_path"],
                "properties": {
                    "artifact_path": { "type": "string" }
                }
            }
        },
        {
            "name": "validate_review_artifact",
            "description": "Validate a saved ReviewArtifact.v1 against its ReviewRequest.v1. Use before trusting or posting an artifact from disk.",
            "inputSchema": {
                "type": "object",
                "required": ["request_path", "artifact_path"],
                "properties": {
                    "request_path": { "type": "string" },
                    "artifact_path": { "type": "string" }
                }
            }
        }
    ])
}

fn call_tool(params: &Value) -> Result<Value> {
    let name = params
        .get("name")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("tools/call missing tool name"))?;
    let arguments = params
        .get("arguments")
        .cloned()
        .unwrap_or_else(|| json!({}));

    match name {
        "review_git_range" => review_git_range(arguments),
        "render_review_artifact" => render_review_artifact(arguments),
        "validate_review_artifact" => validate_review_artifact(arguments),
        other => Err(anyhow!("unknown tool: {other}")),
    }
}

#[derive(Debug, Default, Deserialize)]
struct ReviewGitRangeArgs {
    #[serde(default = "default_repo_path")]
    repo_path: PathBuf,
    base: String,
    #[serde(default = "default_head")]
    head: String,
    base_workspace: Option<PathBuf>,
    title: Option<String>,
    description: Option<String>,
    request_id: Option<String>,
    repo: Option<String>,
    #[serde(default)]
    instructions: Vec<String>,
    #[serde(default)]
    allow_env: Vec<String>,
    #[serde(default)]
    local_runtime_commands: Vec<String>,
    #[serde(default)]
    allow_local_runtime: bool,
    #[serde(default = "default_timeout_seconds")]
    timeout_seconds: u64,
    harness: Option<String>,
    fixture_output: Option<PathBuf>,
    opencode_binary: Option<String>,
    opencode_attach: Option<String>,
    opencode_agent: Option<String>,
    omp_binary: Option<String>,
    model: Option<String>,
    fail_on: Option<String>,
    #[serde(default)]
    json: bool,
}

#[derive(Debug, Deserialize)]
struct RenderArtifactArgs {
    artifact_path: PathBuf,
}

#[derive(Debug, Deserialize)]
struct ValidateArtifactArgs {
    request_path: PathBuf,
    artifact_path: PathBuf,
}

fn review_git_range(arguments: Value) -> Result<Value> {
    let args: ReviewGitRangeArgs =
        serde_json::from_value(arguments).context("parse review_git_range arguments")?;
    let substrate = review_substrate(&args)?;
    let fail_on = args.fail_on.clone();
    let json_output = args.json;
    let timeout_ms = args
        .timeout_seconds
        .checked_mul(1000)
        .ok_or_else(|| anyhow!("timeout_seconds overflows milliseconds"))?;
    let request = build_git_range_request(&GitRangeRequestOptions {
        repo_path: args.repo_path,
        base: args.base,
        head: args.head,
        base_workspace: args.base_workspace,
        title: args.title,
        description: args.description,
        repo: args.repo,
        common: RequestOptions {
            request_id: args.request_id,
            instructions: args.instructions,
            local_runtime: runtime_targets(args.local_runtime_commands),
            allow_local_runtime: args.allow_local_runtime,
            allowed_env: args.allow_env,
            timeout_ms,
        },
    })?;
    validate_request(&request)?;

    let kernel = ReviewKernel::new(substrate);
    let run_policy = RunPolicy {
        cwd: std::env::current_dir().context("read current directory")?,
        timeout: Duration::from_millis(request.policy.timeout_ms),
        failure_transcript: None,
    };
    let run = kernel.review(&request, &run_policy)?;
    validate_artifact_for_request(&run.artifact, &request)?;

    let body = if json_output {
        serde_json::to_string_pretty(&run.artifact)?
    } else {
        render_markdown(&run.artifact)
    };
    Ok(json!({
        "content": [{ "type": "text", "text": body }],
        "structuredContent": {
            "request_id": request.request_id,
            "artifact_id": run.artifact.artifact_id,
            "verdict": run.artifact.verdict,
            "blocking": verdict_blocks(&run.artifact.verdict, fail_on.as_deref())?,
            "context_capabilities": run.artifact.context_capabilities
        }
    }))
}

fn render_review_artifact(arguments: Value) -> Result<Value> {
    let args: RenderArtifactArgs =
        serde_json::from_value(arguments).context("parse render_review_artifact arguments")?;
    let artifact = read_json::<ReviewArtifact>(&args.artifact_path)?;
    Ok(json!({
        "content": [{ "type": "text", "text": render_markdown(&artifact) }],
        "structuredContent": {
            "artifact_id": artifact.artifact_id,
            "verdict": artifact.verdict
        }
    }))
}

fn validate_review_artifact(arguments: Value) -> Result<Value> {
    let args: ValidateArtifactArgs =
        serde_json::from_value(arguments).context("parse validate_review_artifact arguments")?;
    let request = read_json::<ReviewRequest>(&args.request_path)?;
    validate_request(&request)?;
    let artifact = read_json::<ReviewArtifact>(&args.artifact_path)?;
    validate_artifact_for_request(&artifact, &request)?;
    Ok(json!({
        "content": [{
            "type": "text",
            "text": format!("valid ReviewArtifact.v1 `{}` for request `{}`", artifact.artifact_id, request.request_id)
        }],
        "structuredContent": {
            "valid": true,
            "request_id": request.request_id,
            "artifact_id": artifact.artifact_id,
            "verdict": artifact.verdict
        }
    }))
}

fn review_substrate(args: &ReviewGitRangeArgs) -> Result<ReviewSubstrate> {
    match args.harness.as_deref().unwrap_or("opencode") {
        "fixture" => {
            let output = args
                .fixture_output
                .clone()
                .ok_or_else(|| anyhow!("fixture harness requires fixture_output"))?;
            Ok(ReviewSubstrate::Fixture(FixtureSubstrateConfig { output }))
        }
        "opencode" => Ok(ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: args
                .opencode_binary
                .clone()
                .unwrap_or_else(|| "opencode".to_string()),
            attach: args.opencode_attach.clone(),
            agent: Some(
                args.opencode_agent
                    .clone()
                    .unwrap_or_else(|| "build".to_string()),
            ),
            model: args.model.clone(),
        })),
        "omp" => Ok(ReviewSubstrate::Omp(OmpSubstrateConfig {
            binary: args.omp_binary.clone().unwrap_or_else(|| "omp".to_string()),
            model: args.model.clone(),
        })),
        other => Err(anyhow!(
            "unsupported harness {other}; expected one of opencode, omp, fixture"
        )),
    }
}

fn runtime_targets(commands: Vec<String>) -> Vec<RuntimeTarget> {
    commands
        .into_iter()
        .map(|command| RuntimeTarget {
            kind: "command".to_string(),
            command,
            args: Vec::new(),
            cwd: None,
        })
        .collect()
}

fn verdict_blocks(verdict: &Verdict, fail_on: Option<&str>) -> Result<bool> {
    match fail_on.unwrap_or("none") {
        "none" => Ok(false),
        "warn" => Ok(matches!(verdict, Verdict::Warn | Verdict::Fail)),
        "fail" => Ok(matches!(verdict, Verdict::Fail)),
        other => Err(anyhow!(
            "unsupported fail_on {other}; expected none, warn, or fail"
        )),
    }
}

fn read_json<T>(path: &Path) -> Result<T>
where
    T: serde::de::DeserializeOwned,
{
    let text = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    serde_json::from_str(&text).with_context(|| format!("parse JSON {}", path.display()))
}

fn default_repo_path() -> PathBuf {
    PathBuf::from(".")
}

fn default_head() -> String {
    "HEAD".to_string()
}

fn default_timeout_seconds() -> u64 {
    120
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mcp_tools_are_agent_intents_not_cli_mirrors() {
        let tools = tool_defs();
        let names = tools
            .as_array()
            .unwrap()
            .iter()
            .map(|tool| tool["name"].as_str().unwrap())
            .collect::<Vec<_>>();

        assert_eq!(names.len(), 3);
        assert!(names.contains(&"review_git_range"));
        assert!(names.contains(&"render_review_artifact"));
        assert!(names.contains(&"validate_review_artifact"));
    }

    #[test]
    fn verdict_blocking_matches_agent_gate_contract() {
        assert!(!verdict_blocks(&Verdict::Warn, Some("fail")).unwrap());
        assert!(verdict_blocks(&Verdict::Warn, Some("warn")).unwrap());
        assert!(verdict_blocks(&Verdict::Fail, Some("fail")).unwrap());
        assert!(!verdict_blocks(&Verdict::Skip, Some("warn")).unwrap());
    }
}
