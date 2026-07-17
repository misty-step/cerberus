use anyhow::{anyhow, Context, Result};
use serde_json::Value;

use super::CommandInput;

/// Fixed private OMP review config overlay, passed via `--config` on every
/// OMP run. Env-cleared fresh-XDG runs otherwise trigger unbounded
/// fastembed/onnxruntime downloads and unwanted retry/model-fallback
/// behavior; this exact shape (memory backend off, retry disabled, no model
/// fallback) is the one proven stable across 5x live env-clear runs. See
/// docs/plans/productization-2026-07-17.md Phase 0.
pub(super) const OMP_REVIEW_CONFIG_OVERLAY: &str =
    "memory:\n  backend: off\nretry:\n  enabled: false\n  modelFallback: false\n";

pub(super) const OMP_PIN_PATH: &str = "config/omp-version.json";

#[derive(Debug, Clone)]
pub struct OmpSubstrateConfig {
    pub binary: String,
    pub model: Option<String>,
}

/// Build the OMP command for one review attempt. v17.0.2 single-shot
/// headless contract: `-p --mode json` plus every isolation flag, a trusted
/// cwd, and exactly one private prompt reference in argv (never raw
/// prompt/diff content). See docs/plans/productization-2026-07-17.md Phase 0.
pub(super) fn command_args(
    config: &OmpSubstrateConfig,
    input: CommandInput<'_>,
) -> Result<(String, Vec<String>, &'static str, &'static str)> {
    let mut args = vec![
        "-p".to_string(),
        "--mode".to_string(),
        "json".to_string(),
        "--no-session".to_string(),
        "--no-pty".to_string(),
        "--no-extensions".to_string(),
        "--no-skills".to_string(),
        "--no-rules".to_string(),
        "--cwd".to_string(),
        input.cwd.display().to_string(),
        // Private repeatable --config overlay proven to avoid
        // fastembed/onnxruntime downloads and retry/model-fallback
        // surprises on fresh env-cleared XDG state. See
        // OMP_REVIEW_CONFIG_OVERLAY.
        "--config".to_string(),
        input.omp_config_path.display().to_string(),
    ];
    if let Some(model) = &config.model {
        args.push("--model".to_string());
        args.push(model.clone());
    }
    args.push(format!("@{}", input.prompt_path.display()));
    Ok((config.binary.clone(), args, "omp", "private prompt file"))
}

/// Fail-closed check over an OMP `--mode json` run's raw stdout. Process exit
/// status is not trustworthy for this substrate: a live probe showed `omp`
/// exits 0 even when the model's own final message stopped with an error or
/// was aborted. Parses every non-empty line as one NDJSON event, requires
/// exactly one terminal `type == "agent_end"` event, requires that event to
/// carry at least one `role == "assistant"` message, and rejects a final
/// assistant `stopReason` of `error` or `aborted`. OMP emits many other
/// event types along the way; those are intentionally not enumerated here --
/// only `agent_end` is meaningful to this gate.
pub(super) fn validate_lifecycle(stdout: &[u8]) -> Result<()> {
    let text = String::from_utf8_lossy(stdout);
    let mut agent_end_events: Vec<Value> = Vec::new();
    for (index, line) in text.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let event: Value = serde_json::from_str(trimmed).with_context(|| {
            format!("omp stdout line {} is not valid JSON: {trimmed}", index + 1)
        })?;
        if event.get("type").and_then(Value::as_str) == Some("agent_end") {
            agent_end_events.push(event);
        }
    }
    if agent_end_events.len() != 1 {
        return Err(anyhow!(
            "omp lifecycle invalid: expected exactly one agent_end event, observed {}",
            agent_end_events.len()
        ));
    }
    let terminal = &agent_end_events[0];
    let messages = terminal
        .get("messages")
        .and_then(Value::as_array)
        .ok_or_else(|| anyhow!("omp lifecycle invalid: agent_end event has no messages array"))?;
    let final_assistant = messages
        .iter()
        .rev()
        .find(|message| message.get("role").and_then(Value::as_str) == Some("assistant"))
        .ok_or_else(|| {
            anyhow!("omp lifecycle invalid: agent_end event contains no assistant message")
        })?;
    let stop_reason = final_assistant
        .get("stopReason")
        .and_then(Value::as_str)
        .ok_or_else(|| {
            anyhow!("omp lifecycle invalid: final assistant message has no stopReason")
        })?;
    if stop_reason == "error" || stop_reason == "aborted" {
        return Err(anyhow!(
            "omp lifecycle invalid: final assistant stopReason was \"{stop_reason}\""
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn omp_lifecycle_accepts_clean_terminal_stop() {
        let stdout = br#"{"type":"agent_end","messages":[{"role":"assistant","content":[{"type":"text","text":"ok"}],"stopReason":"stop"}]}"#;
        assert!(validate_lifecycle(stdout).is_ok());
    }

    #[test]
    fn omp_lifecycle_rejects_model_error_stop_reason() {
        let stdout = br#"{"type":"agent_end","messages":[{"role":"assistant","content":[],"provider":"zai","stopReason":"error","errorStatus":429}]}"#;
        let err = validate_lifecycle(stdout).unwrap_err();
        assert!(err.to_string().contains("stopReason"));
    }

    #[test]
    fn omp_lifecycle_rejects_missing_terminal_agent_end() {
        let stdout = br#"{"type":"tool_call","name":"grep"}
{"type":"tool_result","ok":true}"#;
        let err = validate_lifecycle(stdout).unwrap_err();
        assert!(err.to_string().contains("agent_end"));
    }

    #[test]
    fn omp_lifecycle_rejects_malformed_json_line() {
        let stdout = b"{not json}\n{\"type\":\"agent_end\",\"messages\":[{\"role\":\"assistant\",\"content\":[],\"stopReason\":\"stop\"}]}";
        let err = validate_lifecycle(stdout).unwrap_err();
        assert!(err.to_string().contains("not valid JSON"));
    }

    #[test]
    fn omp_lifecycle_ignores_unenumerated_nonterminal_event_types_and_blank_lines() {
        let stdout = b"{\"type\":\"tool_call\",\"name\":\"grep\"}\n\n{\"type\":\"some_future_event_kind\",\"foo\":1}\n{\"type\":\"agent_end\",\"messages\":[{\"role\":\"assistant\",\"content\":[],\"stopReason\":\"stop\"}]}\n";
        assert!(validate_lifecycle(stdout).is_ok());
    }
}
