use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;

use super::join_search_path;

#[derive(Debug, Deserialize)]
struct SubstrateVersionPin {
    version: String,
    install: String,
    bump_procedure: String,
}

pub(super) fn verify_substrate_version_pin(
    executable: &Path,
    pin_path: &Path,
    substrate_name: &str,
    trusted_search_path: &[PathBuf],
) -> Result<()> {
    let pin = read_substrate_version_pin(pin_path, substrate_name)?;
    let output = Command::new(executable)
        .arg("--version")
        .stdin(Stdio::null())
        .env_clear()
        .env("PATH", join_search_path(trusted_search_path))
        .output()
        .with_context(|| {
            format!(
                "probe {substrate_name} version with {} --version",
                executable.display()
            )
        })?;
    if !output.status.success() {
        return Err(anyhow!(
            "{substrate_name} version pin check failed: {} --version exited with {}; expected {} from {}. Install the pin with `{}` or follow {}.",
            executable.display(),
            output.status,
            pin.version,
            pin_path.display(),
            pin.install,
            pin.bump_procedure
        ));
    }
    let observed = parse_version_token(&output.stdout)
        .or_else(|| parse_version_token(&output.stderr))
        .ok_or_else(|| {
            anyhow!(
                "{substrate_name} version pin check failed: {} --version did not print a parseable version; expected {} from {}. Follow {} before running live reviews.",
                executable.display(),
                pin.version,
                pin_path.display(),
                pin.bump_procedure
            )
        })?;
    if observed != pin.version {
        return Err(anyhow!(
            "{substrate_name} version drift: expected {} from {}, but {} reported {}. Install the pin with `{}` or update the pin via {} before running live reviews.",
            pin.version,
            pin_path.display(),
            executable.display(),
            observed,
            pin.install,
            pin.bump_procedure
        ));
    }
    Ok(())
}

fn read_substrate_version_pin(path: &Path, substrate_name: &str) -> Result<SubstrateVersionPin> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("read {substrate_name} version pin {}", path.display()))?;
    serde_json::from_str(&raw)
        .with_context(|| format!("parse {substrate_name} version pin {}", path.display()))
}

fn parse_version_token(bytes: &[u8]) -> Option<String> {
    String::from_utf8_lossy(bytes)
        .split_whitespace()
        .filter_map(|raw| {
            let token = raw.rsplit('/').next().unwrap_or(raw);
            let token = token.strip_prefix('v').unwrap_or(token);
            let mut parts = token.split('.');
            let valid = matches!(
                (parts.next(), parts.next(), parts.next()),
                (Some(major), Some(minor), Some(patch))
                    if major.chars().all(|c| c.is_ascii_digit())
                        && minor.chars().all(|c| c.is_ascii_digit())
                        && patch
                            .chars()
                            .take_while(|c| *c != '-' && *c != '+')
                            .all(|c| c.is_ascii_digit())
            );
            valid.then(|| token.to_string())
        })
        .next()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_token_accepts_plain_and_slash_prefixed_versions() {
        assert_eq!(
            parse_version_token(b"opencode 1.2.6\n"),
            Some("1.2.6".to_string())
        );
        assert_eq!(
            parse_version_token(b"omp/17.0.2\n"),
            Some("17.0.2".to_string())
        );
    }
}
