use serde_json::Value;

use crate::schema::{ReviewTelemetry, Usage};

pub(crate) fn opencode_telemetry(stdout: &[u8], model_fallback: Option<&str>) -> ReviewTelemetry {
    let raw = String::from_utf8_lossy(stdout);
    let mut telemetry = ReviewTelemetry::default();
    for line in raw.lines() {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if telemetry.model.is_none() {
            telemetry.model =
                string_at_any(&value, &["/model", "/message/model", "/session/model"]);
        }
        if let Some(usage) = usage_from_event(&value) {
            telemetry.usage = Some(merge_usage(telemetry.usage.take(), usage));
        }
        if telemetry.cost_usd.is_none() {
            telemetry.cost_usd = f64_at_any(&value, &["/cost_usd", "/cost", "/message/cost_usd"]);
        }
    }
    if telemetry.model.is_none() {
        telemetry.model = model_fallback.map(str::to_string);
    }
    if telemetry.cost_usd.is_none() {
        telemetry.cost_usd = telemetry.usage.as_ref().and_then(|usage| usage.cost_usd);
    }
    telemetry
}

pub(crate) fn omp_telemetry(model: Option<&str>) -> ReviewTelemetry {
    ReviewTelemetry {
        model: model.map(str::to_string),
        ..ReviewTelemetry::default()
    }
}

fn usage_from_event(value: &Value) -> Option<Usage> {
    let usage_value = value
        .get("usage")
        .or_else(|| value.pointer("/message/usage"))
        .or_else(|| value.pointer("/response/usage"))?;
    let usage = Usage {
        prompt_tokens: u64_at_any(usage_value, &["/prompt_tokens", "/input_tokens", "/input"]),
        completion_tokens: u64_at_any(
            usage_value,
            &["/completion_tokens", "/output_tokens", "/output"],
        ),
        cost_usd: f64_at_any(usage_value, &["/cost_usd", "/cost"]),
    };
    if usage.prompt_tokens.is_none()
        && usage.completion_tokens.is_none()
        && usage.cost_usd.is_none()
    {
        None
    } else {
        Some(usage)
    }
}

fn merge_usage(previous: Option<Usage>, next: Usage) -> Usage {
    let Some(previous) = previous else {
        return next;
    };
    Usage {
        prompt_tokens: next.prompt_tokens.or(previous.prompt_tokens),
        completion_tokens: next.completion_tokens.or(previous.completion_tokens),
        cost_usd: next.cost_usd.or(previous.cost_usd),
    }
}

fn string_at_any(value: &Value, pointers: &[&str]) -> Option<String> {
    pointers
        .iter()
        .find_map(|pointer| value.pointer(pointer).and_then(Value::as_str))
        .map(str::to_string)
}

fn u64_at_any(value: &Value, pointers: &[&str]) -> Option<u64> {
    pointers.iter().find_map(|pointer| {
        value.pointer(pointer).and_then(|value| {
            value
                .as_u64()
                .or_else(|| value.as_str().and_then(|raw| raw.parse::<u64>().ok()))
        })
    })
}

fn f64_at_any(value: &Value, pointers: &[&str]) -> Option<f64> {
    pointers.iter().find_map(|pointer| {
        value.pointer(pointer).and_then(|value| {
            value
                .as_f64()
                .or_else(|| value.as_str().and_then(|raw| raw.parse::<f64>().ok()))
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opencode_json_events_extract_model_usage_and_cost() {
        let stdout = br#"{"type":"metadata","model":"fake/opencode-reviewer","usage":{"prompt_tokens":123,"completion_tokens":45,"cost_usd":0.0042}}"#;

        let telemetry = opencode_telemetry(stdout, None);

        assert_eq!(telemetry.model.as_deref(), Some("fake/opencode-reviewer"));
        let usage = telemetry.usage.unwrap();
        assert_eq!(usage.prompt_tokens, Some(123));
        assert_eq!(usage.completion_tokens, Some(45));
        assert_eq!(usage.cost_usd, Some(0.0042));
        assert_eq!(telemetry.cost_usd, Some(0.0042));
    }

    #[test]
    fn opencode_telemetry_uses_config_model_when_events_omit_model() {
        let stdout = br#"{"type":"metadata","usage":{"input_tokens":"12","output_tokens":"3"}}"#;

        let telemetry = opencode_telemetry(stdout, Some("configured/model"));

        assert_eq!(telemetry.model.as_deref(), Some("configured/model"));
        let usage = telemetry.usage.unwrap();
        assert_eq!(usage.prompt_tokens, Some(12));
        assert_eq!(usage.completion_tokens, Some(3));
    }

    #[test]
    fn omp_telemetry_records_configured_model_only() {
        let telemetry = omp_telemetry(Some("omp/model"));

        assert_eq!(telemetry.model.as_deref(), Some("omp/model"));
        assert!(telemetry.usage.is_none());
        assert!(telemetry.cost_usd.is_none());
    }
}
