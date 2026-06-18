use crate::SchemaError;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const LEGACY_SURFACE_INVENTORY_VERSION: &str = "legacy-surface-inventory.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LegacySurfaceInventory {
    pub schema_version: String,
    pub snapshot_date: String,
    pub purpose: String,
    pub surfaces: Vec<LegacySurface>,
}

impl LegacySurfaceInventory {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            LEGACY_SURFACE_INVENTORY_VERSION,
        )?;
        non_empty("snapshot_date", &self.snapshot_date)?;
        non_empty("purpose", &self.purpose)?;
        if self.surfaces.is_empty() {
            return Err(SchemaError::Missing { field: "surfaces" });
        }

        let mut surface_ids = BTreeSet::new();
        for surface in &self.surfaces {
            surface.validate()?;
            if !surface_ids.insert(surface.surface_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "surfaces.surface_id",
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LegacySurface {
    pub surface_id: String,
    pub paths: Vec<String>,
    pub current_responsibility: String,
    pub retirement_decision: LegacyRetirementDecision,
    pub parity_status: LegacyParityStatus,
    #[serde(default)]
    pub rust_replacement: Option<String>,
    #[serde(default)]
    pub keep_reason: Option<String>,
    #[serde(default)]
    pub parity_evidence: Vec<String>,
    #[serde(default)]
    pub deletion_or_archive_commit: Option<String>,
    pub rollback_path: String,
    pub next_action: String,
}

impl LegacySurface {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("surface_id", &self.surface_id)?;
        non_empty("current_responsibility", &self.current_responsibility)?;
        non_empty("rollback_path", &self.rollback_path)?;
        non_empty("next_action", &self.next_action)?;
        if self.paths.is_empty() {
            return Err(SchemaError::Missing { field: "paths" });
        }
        let mut paths = BTreeSet::new();
        for path in &self.paths {
            non_empty("paths", path)?;
            if !paths.insert(path.as_str()) {
                return Err(SchemaError::Inconsistent { field: "paths" });
            }
        }
        for evidence in &self.parity_evidence {
            non_empty("parity_evidence", evidence)?;
        }
        if let Some(commit) = &self.deletion_or_archive_commit {
            non_empty("deletion_or_archive_commit", commit)?;
            if matches!(
                self.parity_status,
                LegacyParityStatus::Pending | LegacyParityStatus::CompatibilityOnly
            ) {
                return Err(SchemaError::Inconsistent {
                    field: "deletion_or_archive_commit",
                });
            }
        }

        match self.retirement_decision {
            LegacyRetirementDecision::KeepCompatibility => {
                require_present("keep_reason", self.keep_reason.as_deref())?;
            }
            LegacyRetirementDecision::PortToRust | LegacyRetirementDecision::DeleteAfterParity => {
                require_present("rust_replacement", self.rust_replacement.as_deref())?;
            }
            LegacyRetirementDecision::ArchiveAfterParity => {
                match (
                    self.rust_replacement.as_deref(),
                    self.keep_reason.as_deref(),
                ) {
                    (Some(replacement), _) if !replacement.trim().is_empty() => {}
                    (_, Some(reason)) if !reason.trim().is_empty() => {}
                    _ => {
                        return Err(SchemaError::Missing {
                            field: "rust_replacement",
                        });
                    }
                }
            }
        }

        if matches!(
            self.parity_status,
            LegacyParityStatus::CoveredByRustFixture | LegacyParityStatus::IntentionallyRejected
        ) && self.parity_evidence.is_empty()
        {
            return Err(SchemaError::Missing {
                field: "parity_evidence",
            });
        }

        if self.parity_status == LegacyParityStatus::CompatibilityOnly
            && self.retirement_decision != LegacyRetirementDecision::KeepCompatibility
        {
            return Err(SchemaError::Inconsistent {
                field: "parity_status",
            });
        }

        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LegacyRetirementDecision {
    KeepCompatibility,
    PortToRust,
    ArchiveAfterParity,
    DeleteAfterParity,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LegacyParityStatus {
    Pending,
    CoveredByRustFixture,
    IntentionallyRejected,
    CompatibilityOnly,
}

fn require_present(field: &'static str, value: Option<&str>) -> Result<(), SchemaError> {
    match value {
        Some(value) => non_empty(field, value),
        None => Err(SchemaError::Missing { field }),
    }
}

fn non_empty(field: &'static str, value: &str) -> Result<(), SchemaError> {
    if value.trim().is_empty() {
        Err(SchemaError::Empty { field })
    } else {
        Ok(())
    }
}

fn expect_version(
    field: &'static str,
    actual: &str,
    expected: &'static str,
) -> Result<(), SchemaError> {
    if actual == expected {
        Ok(())
    } else {
        Err(SchemaError::Version {
            field,
            actual: actual.to_string(),
            expected,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_surface_inventory_accepts_checked_plan() {
        inventory().validate().expect("inventory validates");
    }

    #[test]
    fn legacy_surface_inventory_rejects_duplicate_surface_ids() {
        let mut inventory = inventory();
        inventory.surfaces.push(inventory.surfaces[0].clone());

        assert!(matches!(
            inventory.validate(),
            Err(SchemaError::Inconsistent {
                field: "surfaces.surface_id"
            })
        ));
    }

    #[test]
    fn legacy_surface_requires_replacement_for_port() {
        let mut inventory = inventory();
        inventory.surfaces[1].rust_replacement = None;

        assert!(matches!(
            inventory.validate(),
            Err(SchemaError::Missing {
                field: "rust_replacement"
            })
        ));
    }

    #[test]
    fn legacy_surface_requires_reason_for_compatibility_keep() {
        let mut inventory = inventory();
        inventory.surfaces[0].keep_reason = None;

        assert!(matches!(
            inventory.validate(),
            Err(SchemaError::Missing {
                field: "keep_reason"
            })
        ));
    }

    #[test]
    fn legacy_surface_rejects_archive_commit_without_parity() {
        let mut inventory = inventory();
        inventory.surfaces[1].deletion_or_archive_commit = Some("abc1234".to_string());

        assert!(matches!(
            inventory.validate(),
            Err(SchemaError::Inconsistent {
                field: "deletion_or_archive_commit"
            })
        ));
    }

    #[test]
    fn legacy_surface_requires_non_empty_archive_replacement_or_reason() {
        let mut inventory = inventory();
        inventory.surfaces.push(LegacySurface {
            surface_id: "empty-archive".to_string(),
            paths: vec!["README.md".to_string()],
            current_responsibility: "Historical surface.".to_string(),
            retirement_decision: LegacyRetirementDecision::ArchiveAfterParity,
            parity_status: LegacyParityStatus::Pending,
            rust_replacement: Some("   ".to_string()),
            keep_reason: Some(String::new()),
            parity_evidence: vec![],
            deletion_or_archive_commit: None,
            rollback_path: "Restore from archive commit.".to_string(),
            next_action: "Add a real reason.".to_string(),
        });

        assert!(matches!(
            inventory.validate(),
            Err(SchemaError::Missing {
                field: "rust_replacement"
            })
        ));
    }

    fn inventory() -> LegacySurfaceInventory {
        LegacySurfaceInventory {
            schema_version: LEGACY_SURFACE_INVENTORY_VERSION.to_string(),
            snapshot_date: "2026-06-18".to_string(),
            purpose: "Test legacy retirement inventory.".to_string(),
            surfaces: vec![
                LegacySurface {
                    surface_id: "root-github-action".to_string(),
                    paths: vec!["action.yml".to_string()],
                    current_responsibility: "Public GitHub Action entrypoint.".to_string(),
                    retirement_decision: LegacyRetirementDecision::KeepCompatibility,
                    parity_status: LegacyParityStatus::CompatibilityOnly,
                    rust_replacement: None,
                    keep_reason: Some("Public consumers still call the root action.".to_string()),
                    parity_evidence: vec![],
                    deletion_or_archive_commit: None,
                    rollback_path: "Restore action.yml from the previous release tag.".to_string(),
                    next_action: "Keep aligned with dispatch compatibility.".to_string(),
                },
                LegacySurface {
                    surface_id: "elixir-review-engine".to_string(),
                    paths: vec!["cerberus-elixir/lib/cerberus/engine.ex".to_string()],
                    current_responsibility: "Legacy reviewer orchestration.".to_string(),
                    retirement_decision: LegacyRetirementDecision::PortToRust,
                    parity_status: LegacyParityStatus::Pending,
                    rust_replacement: Some(
                        "crates/cerberus-core reviewer execution path".to_string(),
                    ),
                    keep_reason: None,
                    parity_evidence: vec![],
                    deletion_or_archive_commit: None,
                    rollback_path: "Keep cerberus-elixir tests passing until parity.".to_string(),
                    next_action: "Port orchestration fixtures to Rust.".to_string(),
                },
            ],
        }
    }
}
