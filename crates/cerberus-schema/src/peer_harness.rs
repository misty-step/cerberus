use crate::SchemaError;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const PEER_HARNESS_COMMAND_PROFILES_VERSION: &str = "peer-harness-command-profiles.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PeerHarnessCommandProfiles {
    pub schema_version: String,
    pub observed_at: String,
    pub profiles: Vec<PeerHarnessCommandProfile>,
}

impl PeerHarnessCommandProfiles {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            PEER_HARNESS_COMMAND_PROFILES_VERSION,
        )?;
        non_empty("observed_at", &self.observed_at)?;
        if self.profiles.is_empty() {
            return Err(SchemaError::Missing { field: "profiles" });
        }

        let mut harness_ids = BTreeSet::new();
        for profile in &self.profiles {
            profile.validate()?;
            if !harness_ids.insert(profile.harness_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "profiles.harness_id",
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PeerHarnessCommandProfile {
    pub harness_id: String,
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    pub timeout_ms: u64,
    #[serde(default)]
    pub env_required: Vec<String>,
    pub output_contract: PeerHarnessOutputContract,
    pub peer: PeerHarnessInvocation,
    #[serde(default)]
    pub unsupported: Vec<String>,
    #[serde(default)]
    pub notes: Option<String>,
}

impl PeerHarnessCommandProfile {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("harness_id", &self.harness_id)?;
        non_empty("command", &self.command)?;
        expect_range("timeout_ms", self.timeout_ms as f64, 1.0, 3_600_000.0)?;
        validate_non_empty_items("args", &self.args)?;
        validate_env_names(&self.env_required)?;
        validate_runner_boundary(self)?;
        self.peer.validate()?;
        if self.unsupported.is_empty() {
            return Err(SchemaError::Missing {
                field: "unsupported",
            });
        }
        validate_non_empty_items("unsupported", &self.unsupported)?;
        validate_unique_items("unsupported", &self.unsupported)?;
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PeerHarnessInvocation {
    pub command: String,
    #[serde(default)]
    pub args_template: Vec<String>,
    pub prompt_mode: PeerHarnessPromptMode,
    #[serde(default)]
    pub notes: Option<String>,
}

impl PeerHarnessInvocation {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("peer.command", &self.command)?;
        validate_non_empty_items("peer.args_template", &self.args_template)?;
        match self.prompt_mode {
            PeerHarnessPromptMode::ArgvMessage | PeerHarnessPromptMode::WrapperRenderedPrompt => {
                if self.args_template.is_empty() {
                    return Err(SchemaError::Missing {
                        field: "peer.args_template",
                    });
                }
                expect_exact_placeholder_count(
                    "peer.args_template",
                    &self.args_template,
                    "{prompt}",
                    1,
                )?;
                if !self
                    .args_template
                    .iter()
                    .any(|argument| argument == "{prompt}")
                {
                    return Err(SchemaError::Inconsistent {
                        field: "peer.args_template",
                    });
                }
                Ok(())
            }
            PeerHarnessPromptMode::StdinText => {
                if placeholder_count(&self.args_template, "{prompt}") > 0 {
                    return Err(SchemaError::Inconsistent {
                        field: "peer.args_template",
                    });
                }
                Ok(())
            }
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PeerHarnessOutputContract {
    ReviewerArtifactFile,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PeerHarnessPromptMode {
    ArgvMessage,
    StdinText,
    WrapperRenderedPrompt,
}

fn validate_env_names(values: &[String]) -> Result<(), SchemaError> {
    let mut seen = BTreeSet::new();
    for value in values {
        non_empty("env_required", value)?;
        if !seen.insert(value.as_str()) {
            return Err(SchemaError::Inconsistent {
                field: "env_required",
            });
        }
        if !is_env_name(value) {
            return Err(SchemaError::Inconsistent {
                field: "env_required",
            });
        }
    }
    Ok(())
}

fn validate_runner_boundary(profile: &PeerHarnessCommandProfile) -> Result<(), SchemaError> {
    if profile.command == profile.peer.command {
        return Err(SchemaError::Inconsistent { field: "command" });
    }
    if profile.command != "cerberus-peer-harness" {
        return Err(SchemaError::Inconsistent { field: "command" });
    }
    if profile.args != ["--harness".to_string(), profile.harness_id.clone()] {
        return Err(SchemaError::Inconsistent { field: "args" });
    }
    Ok(())
}

fn validate_non_empty_items(field: &'static str, values: &[String]) -> Result<(), SchemaError> {
    for value in values {
        non_empty(field, value)?;
    }
    Ok(())
}

fn validate_unique_items(field: &'static str, values: &[String]) -> Result<(), SchemaError> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !seen.insert(value.as_str()) {
            return Err(SchemaError::Inconsistent { field });
        }
    }
    Ok(())
}

fn expect_exact_placeholder_count(
    field: &'static str,
    values: &[String],
    placeholder: &str,
    expected: usize,
) -> Result<(), SchemaError> {
    let count = placeholder_count(values, placeholder);
    if count != expected {
        return Err(SchemaError::Inconsistent { field });
    }
    Ok(())
}

fn placeholder_count(values: &[String], placeholder: &str) -> usize {
    values
        .iter()
        .map(|value| value.matches(placeholder).count())
        .sum()
}

fn is_env_name(value: &str) -> bool {
    let mut chars = value.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !(first == '_' || first.is_ascii_uppercase()) {
        return false;
    }
    chars.all(|character| {
        character == '_' || character.is_ascii_uppercase() || character.is_ascii_digit()
    })
}

fn non_empty(field: &'static str, value: &str) -> Result<(), SchemaError> {
    if value.trim().is_empty() {
        return Err(SchemaError::Empty { field });
    }
    Ok(())
}

fn expect_version(
    field: &'static str,
    actual: &str,
    expected: &'static str,
) -> Result<(), SchemaError> {
    if actual != expected {
        return Err(SchemaError::Version {
            field,
            actual: actual.to_string(),
            expected,
        });
    }
    Ok(())
}

fn expect_range(field: &'static str, actual: f64, min: f64, max: f64) -> Result<(), SchemaError> {
    if actual < min || actual > max {
        return Err(SchemaError::OutOfRange {
            field,
            min,
            max,
            actual,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const PEER_PROFILES: &str =
        include_str!("../../../fixtures/harnesses/peer-command-profiles.json");

    #[test]
    fn peer_harness_command_profiles_fixture_validates() {
        let profiles: PeerHarnessCommandProfiles =
            serde_json::from_str(PEER_PROFILES).expect("fixture parses");

        profiles.validate().expect("fixture validates");
    }

    #[test]
    fn peer_harness_command_profiles_reject_duplicate_harness_ids() {
        let mut profiles: PeerHarnessCommandProfiles =
            serde_json::from_str(PEER_PROFILES).expect("fixture parses");
        profiles.profiles[1].harness_id = profiles.profiles[0].harness_id.clone();
        profiles.profiles[1].args = profiles.profiles[0].args.clone();

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent {
                field: "profiles.harness_id"
            })
        ));
    }

    #[test]
    fn peer_harness_command_profiles_reject_empty_args_and_bad_env_names() {
        let mut profiles: PeerHarnessCommandProfiles =
            serde_json::from_str(PEER_PROFILES).expect("fixture parses");
        profiles.profiles[0].args.push(String::new());

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Empty { field: "args" })
        ));

        profiles.profiles[0].args.pop();
        profiles.profiles[0]
            .env_required
            .push("openrouter_key".to_string());

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent {
                field: "env_required"
            })
        ));
    }

    #[test]
    fn peer_harness_command_profiles_require_unsupported_boundaries() {
        let mut profiles: PeerHarnessCommandProfiles =
            serde_json::from_str(PEER_PROFILES).expect("fixture parses");
        profiles.profiles[0].unsupported.clear();

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Missing {
                field: "unsupported"
            })
        ));
    }

    #[test]
    fn peer_harness_command_profiles_reject_raw_peer_command_as_runner() {
        let mut profiles: PeerHarnessCommandProfiles =
            serde_json::from_str(PEER_PROFILES).expect("fixture parses");
        profiles.profiles[0].command = profiles.profiles[0].peer.command.clone();

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent { field: "command" })
        ));
    }

    #[test]
    fn peer_harness_command_profiles_require_runner_harness_arg() {
        let mut profiles: PeerHarnessCommandProfiles =
            serde_json::from_str(PEER_PROFILES).expect("fixture parses");
        profiles.profiles[0].args = vec!["--other".to_string(), "pi".to_string()];

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent { field: "args" })
        ));

        profiles.profiles[0].args = vec![
            "--unused".to_string(),
            "value".to_string(),
            "--harness".to_string(),
            "pi".to_string(),
        ];

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent { field: "args" })
        ));
    }

    #[test]
    fn peer_harness_command_profiles_require_one_prompt_placeholder_for_argv_mode() {
        let mut profiles: PeerHarnessCommandProfiles =
            serde_json::from_str(PEER_PROFILES).expect("fixture parses");
        profiles.profiles[0]
            .peer
            .args_template
            .retain(|value| value != "{prompt}");

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent {
                field: "peer.args_template"
            })
        ));

        profiles.profiles[0]
            .peer
            .args_template
            .push("{prompt}".to_string());
        profiles.profiles[0]
            .peer
            .args_template
            .push("{prompt}".to_string());

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent {
                field: "peer.args_template"
            })
        ));

        profiles.profiles[0]
            .peer
            .args_template
            .retain(|value| value != "{prompt}");
        profiles.profiles[0]
            .peer
            .args_template
            .push("--message={prompt}".to_string());

        assert!(matches!(
            profiles.validate(),
            Err(SchemaError::Inconsistent {
                field: "peer.args_template"
            })
        ));
    }
}
