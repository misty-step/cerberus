//! Subscription-first / OpenRouter-denied-by-default trusted review policy
//! (Phase 1, cerberus-051; see docs/plans/productization-2026-07-17.md).
//!
//! Cerberus's trusted (non-container) review path forwarded any OpenRouter
//! model as long as the credential was allowlisted -- no policy ever asked
//! whether OpenRouter should be reachable at all for a given call site. This
//! module closes that gap with a deny-by-default admission check: a resolved
//! model that routes through OpenRouter (`openrouter/...`) is rejected unless
//! an explicit, reviewed, tamper-evident exception record names a scope wide
//! enough to cover the call site.
//!
//! Per ADR 0003 ("the deterministic waist vs. model judgment"), this is
//! exactly the kind of check Rust may own: "does a covering exception exist
//! and self-verify" is a non-AI oracle with a certain yes/no answer. *Which*
//! models or providers deserve an exception is never Cerberus's call --
//! that judgment belongs entirely to whoever authors and reviews the
//! exception file out of band. Rust never hardcodes a model or provider
//! allowlist here.

use std::fmt;
use std::fs;
use std::path::Path;

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

use crate::digest::sha256_digest;
use crate::kernel::ReviewSubstrate;
use crate::schema::ReviewRequest;

/// What an `OpenRouterException` authorizes. A closed, explicit enum so a
/// narrow carve-out can never silently widen into a blanket exception just
/// because an operator reused a file for a different call site.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OpenRouterExceptionScope {
    /// Permits OpenRouter routing for any substrate/call site this policy
    /// gates.
    Any,
    /// Permits OpenRouter routing only for the OpenCode substrate. OpenCode
    /// is the substrate docs/plans/productization-2026-07-17.md Phase 1
    /// calls "the fallback lane": subscription-backed live smoke is
    /// preferred, and this narrower scope is the alternative proof gate when
    /// that isn't available. It never satisfies a check raised for a
    /// different substrate (e.g. OMP).
    OpencodeFallback,
}

impl OpenRouterExceptionScope {
    /// Does a grant of `self` satisfy a check that requires `required`?
    /// `Any` covers everything; every other scope covers only itself.
    fn covers(self, required: OpenRouterExceptionScope) -> bool {
        self == OpenRouterExceptionScope::Any || self == required
    }
}

impl fmt::Display for OpenRouterExceptionScope {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let label = match self {
            OpenRouterExceptionScope::Any => "any",
            OpenRouterExceptionScope::OpencodeFallback => "opencode_fallback",
        };
        f.write_str(label)
    }
}

/// The fields an exception's content digest is computed over. Kept as its
/// own type (rather than reusing `OpenRouterException` and skipping
/// `digest`) so the payload shape used to compute and to verify the digest
/// can never drift apart.
#[derive(Serialize)]
struct OpenRouterExceptionPayload<'a> {
    scope: OpenRouterExceptionScope,
    reason: &'a str,
    approved_by: &'a str,
}

/// A reviewed, digested exception to the OpenRouter deny-by-default policy.
///
/// This is a schema-checked admission artifact, not a place to encode which
/// models or providers are judged acceptable. An operator authors and
/// reviews this file out of band (typically checked into the repo, or
/// supplied via an explicit path for a one-off exception); Cerberus only
/// checks that it exists, parses, is scoped widely enough for the call site,
/// and has not been hand-edited since its digest was computed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OpenRouterException {
    pub scope: OpenRouterExceptionScope,
    /// Free-text justification recorded when the exception was approved.
    /// Never consulted for correctness -- pure provenance.
    pub reason: String,
    /// Who reviewed and approved this exception (name, handle, or similar).
    pub approved_by: String,
    /// sha256 hex digest (see [`crate::digest::sha256_digest`]) over the
    /// canonical JSON of `{scope, reason, approved_by}`, computed by whoever
    /// authored this record and re-verified on every load. Editing `scope`,
    /// `reason`, or `approved_by` without recomputing this digest makes the
    /// record self-evidently tampered, so Cerberus can refuse it
    /// deterministically instead of trusting arbitrary JSON on disk.
    pub digest: String,
}

impl OpenRouterException {
    /// Compute the content digest for the given fields. Used both to author
    /// a new exception record and to verify one on load.
    pub fn compute_digest(
        scope: OpenRouterExceptionScope,
        reason: &str,
        approved_by: &str,
    ) -> Result<String> {
        let payload = OpenRouterExceptionPayload {
            scope,
            reason,
            approved_by,
        };
        let bytes = serde_json::to_vec(&payload)
            .context("serialize OpenRouter exception payload for digesting")?;
        Ok(sha256_digest(bytes))
    }

    fn verify_digest(&self) -> Result<()> {
        let expected = Self::compute_digest(self.scope, &self.reason, &self.approved_by)?;
        if expected != self.digest {
            return Err(anyhow!(
                "OpenRouter exception content digest mismatch: expected {expected}, got {}; \
                 the record was edited without recomputing its digest over \
                 {{scope, reason, approved_by}} -- recompute via \
                 OpenRouterException::compute_digest and update the file",
                self.digest
            ));
        }
        Ok(())
    }

    /// Load and self-verify an exception record from an explicit file path.
    /// No ambient or default path is ever consulted -- callers must name the
    /// file explicitly, matching the house `--gh-token-file`-style pattern
    /// of explicit-source-only trust.
    pub fn load(path: &Path) -> Result<Self> {
        let raw = fs::read_to_string(path)
            .with_context(|| format!("read OpenRouter exception file {}", path.display()))?;
        let record: OpenRouterException = serde_json::from_str(&raw)
            .with_context(|| format!("parse OpenRouter exception file {}", path.display()))?;
        record
            .verify_digest()
            .with_context(|| format!("verify OpenRouter exception file {}", path.display()))?;
        Ok(record)
    }

    fn covers(&self, required: OpenRouterExceptionScope) -> bool {
        self.scope.covers(required)
    }
}

/// Which [`OpenRouterExceptionScope`] a substrate call site requires, and
/// the model it resolved (if the substrate is configured to run at all).
/// `None` means this substrate/config combination never launches a
/// Cerberus-controlled model call, so no policy check applies.
fn openrouter_admission_target(
    substrate: &ReviewSubstrate,
) -> Option<(&'static str, &str, OpenRouterExceptionScope)> {
    match substrate {
        ReviewSubstrate::Opencode(config) => {
            // Attaching to an existing session never launches a new model
            // call under Cerberus's own credential threading; nothing to
            // gate here.
            if config.attach.is_some() {
                return None;
            }
            let model = config.model.as_deref()?;
            Some((
                "opencode",
                model,
                OpenRouterExceptionScope::OpencodeFallback,
            ))
        }
        ReviewSubstrate::Omp(config) => {
            let model = config.model.as_deref()?;
            Some(("omp", model, OpenRouterExceptionScope::Any))
        }
        // Fixture never calls a model. ContainerOpencode is the untrusted-PR
        // sandbox path with its own scoped-key credential model (backlog
        // 013 M1, src/openrouter_keys.rs) and is out of scope for this
        // trusted-path policy.
        ReviewSubstrate::Fixture(_) | ReviewSubstrate::ContainerOpencode(_) => None,
    }
}

/// Deny-by-default admission check plus the pre-existing credential-hygiene
/// check, for both the OpenCode and OMP substrates.
///
/// Order matters: the credential check runs first and is unchanged from the
/// pre-cerberus-051 behavior, so a request missing `OPENROUTER_API_KEY` from
/// its allowed-env list still gets that exact, actionable error regardless
/// of exception state. Only once the credential is present does the new
/// policy check run: an OpenRouter-routed model is rejected unless
/// `exception` is `Some` and its scope covers the call site's required
/// scope.
pub fn require_openrouter_policy_for_substrate(
    request: &ReviewRequest,
    substrate: &ReviewSubstrate,
    exception: Option<&OpenRouterException>,
) -> Result<()> {
    let Some((context, model, required_scope)) = openrouter_admission_target(substrate) else {
        return Ok(());
    };
    // Case-insensitive: a substrate/model resolver that accepts
    // "OpenRouter/..." or "OPENROUTER/..." must not bypass the deny-by-
    // default policy just because Rust's own comparison was case-sensitive.
    if !model.to_ascii_lowercase().starts_with("openrouter/") {
        return Ok(());
    }
    if !request
        .policy
        .allowed_env
        .iter()
        .any(|key| key == "OPENROUTER_API_KEY")
    {
        return Err(anyhow!(
            "{context} OpenRouter model {model:?} requires OPENROUTER_API_KEY in Cerberus's \
             scrubbed child environment; pass --allow-env OPENROUTER_API_KEY or include it in \
             request.policy.allowed_env"
        ));
    }
    match exception {
        Some(exception) if exception.covers(required_scope) => Ok(()),
        Some(exception) => Err(anyhow!(
            "{context} OpenRouter model {model:?} is denied by the subscription-first trusted \
             review policy: the supplied --openrouter-exception-file is scoped to \
             {}, which does not cover the {context} call site's required scope {required_scope}",
            exception.scope
        )),
        None => Err(anyhow!(
            "{context} OpenRouter model {model:?} is denied by the subscription-first trusted \
             review policy (docs/plans/productization-2026-07-17.md Phase 1); pass \
             --openrouter-exception-file <path> naming a reviewed, digested exception record \
             scoped to {required_scope} or wider"
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::harness::{OmpSubstrateConfig, OpenCodeSubstrateConfig};
    use crate::schema::ReviewPolicy;
    use std::path::PathBuf;

    fn openrouter_request(allowed_env: Vec<String>) -> ReviewRequest {
        let request_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/requests/diff-only.json");
        let mut request: ReviewRequest = serde_json::from_str(
            &fs::read_to_string(&request_path).expect("fixture request reads"),
        )
        .expect("fixture request parses");
        request.policy = ReviewPolicy {
            allowed_env,
            ..ReviewPolicy::default()
        };
        request
    }

    fn opencode_openrouter_substrate() -> ReviewSubstrate {
        ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: None,
            agent: Some("build".to_string()),
            model: Some("openrouter/z-ai/glm-5.2".to_string()),
        })
    }

    fn omp_openrouter_substrate() -> ReviewSubstrate {
        ReviewSubstrate::Omp(OmpSubstrateConfig {
            binary: "omp".to_string(),
            model: Some("openrouter/z-ai/glm-5.2".to_string()),
        })
    }

    fn scoped_exception(scope: OpenRouterExceptionScope) -> OpenRouterException {
        let reason = "test fixture exception";
        let approved_by = "test-suite";
        let digest = OpenRouterException::compute_digest(scope, reason, approved_by)
            .expect("digest computes");
        OpenRouterException {
            scope,
            reason: reason.to_string(),
            approved_by: approved_by.to_string(),
            digest,
        }
    }

    // --- deny-by-default: no exception, either substrate -----------------

    #[test]
    fn opencode_openrouter_model_is_denied_without_an_exception() {
        let request = openrouter_request(vec!["OPENROUTER_API_KEY".to_string()]);
        let err = require_openrouter_policy_for_substrate(
            &request,
            &opencode_openrouter_substrate(),
            None,
        )
        .unwrap_err();
        assert!(
            err.to_string()
                .contains("denied by the subscription-first trusted review policy"),
            "error should name the policy that blocked it: {err}"
        );
        assert!(
            err.to_string().contains("--openrouter-exception-file"),
            "error should name the concrete fix: {err}"
        );
    }

    #[test]
    fn omp_openrouter_model_is_denied_without_an_exception() {
        let request = openrouter_request(vec!["OPENROUTER_API_KEY".to_string()]);
        let err =
            require_openrouter_policy_for_substrate(&request, &omp_openrouter_substrate(), None)
                .unwrap_err();
        assert!(
            err.to_string()
                .contains("denied by the subscription-first trusted review policy"),
            "OMP must be gated the same as OpenCode, not silently exempt: {err}"
        );
    }

    // --- existing credential-hygiene check stays authoritative first -----

    #[test]
    fn openrouter_model_without_allowed_key_is_a_clear_preflight_error_before_policy() {
        let request = openrouter_request(Vec::new());
        let err = require_openrouter_policy_for_substrate(
            &request,
            &opencode_openrouter_substrate(),
            None,
        )
        .unwrap_err();
        assert!(
            err.to_string().contains("--allow-env OPENROUTER_API_KEY"),
            "missing credential should still fail with the original, policy-independent fix: {err}"
        );
    }

    // --- explicit-exception path: a covering exception is admitted -------

    #[test]
    fn opencode_openrouter_model_passes_with_an_any_scoped_exception() {
        let request = openrouter_request(vec!["OPENROUTER_API_KEY".to_string()]);
        let exception = scoped_exception(OpenRouterExceptionScope::Any);
        require_openrouter_policy_for_substrate(
            &request,
            &opencode_openrouter_substrate(),
            Some(&exception),
        )
        .unwrap();
    }

    #[test]
    fn omp_openrouter_model_passes_with_an_any_scoped_exception() {
        let request = openrouter_request(vec!["OPENROUTER_API_KEY".to_string()]);
        let exception = scoped_exception(OpenRouterExceptionScope::Any);
        require_openrouter_policy_for_substrate(
            &request,
            &omp_openrouter_substrate(),
            Some(&exception),
        )
        .unwrap();
    }

    // --- OpenCode-fallback-scoped exception: narrow, substrate-specific --

    #[test]
    fn opencode_openrouter_model_passes_with_an_opencode_fallback_scoped_exception() {
        let request = openrouter_request(vec!["OPENROUTER_API_KEY".to_string()]);
        let exception = scoped_exception(OpenRouterExceptionScope::OpencodeFallback);
        require_openrouter_policy_for_substrate(
            &request,
            &opencode_openrouter_substrate(),
            Some(&exception),
        )
        .unwrap();
    }

    #[test]
    fn omp_openrouter_model_is_still_denied_by_an_opencode_fallback_scoped_exception() {
        let request = openrouter_request(vec!["OPENROUTER_API_KEY".to_string()]);
        let exception = scoped_exception(OpenRouterExceptionScope::OpencodeFallback);
        let err = require_openrouter_policy_for_substrate(
            &request,
            &omp_openrouter_substrate(),
            Some(&exception),
        )
        .unwrap_err();
        assert!(
            err.to_string().contains("does not cover"),
            "a fallback-scoped exception must not leak into covering OMP: {err}"
        );
    }

    // --- non-OpenRouter models and attach substrates are unaffected -------

    #[test]
    fn openrouter_model_with_mixed_case_prefix_is_still_gated() {
        let request = openrouter_request(vec!["OPENROUTER_API_KEY".to_string()]);
        let substrate = ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: None,
            agent: Some("build".to_string()),
            model: Some("OpenRouter/z-ai/glm-5.2".to_string()),
        });
        let err = require_openrouter_policy_for_substrate(&request, &substrate, None).unwrap_err();
        assert!(
            err.to_string()
                .contains("denied by the subscription-first trusted review policy"),
            "a case-varied OpenRouter prefix must not bypass the deny-by-default policy: {err}"
        );
    }

    #[test]
    fn non_openrouter_model_is_never_gated() {
        let request = openrouter_request(Vec::new());
        let substrate = ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: None,
            agent: Some("build".to_string()),
            model: Some("anthropic/claude-sonnet".to_string()),
        });
        require_openrouter_policy_for_substrate(&request, &substrate, None).unwrap();
    }

    #[test]
    fn attaching_to_an_existing_opencode_session_is_never_gated() {
        let request = openrouter_request(Vec::new());
        let substrate = ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: Some("existing-session".to_string()),
            agent: Some("build".to_string()),
            model: Some("openrouter/z-ai/glm-5.2".to_string()),
        });
        require_openrouter_policy_for_substrate(&request, &substrate, None).unwrap();
    }

    // --- exception record loading and digest verification ----------------

    #[test]
    fn exception_load_rejects_a_tampered_scope() {
        let dir = tempfile::tempdir().expect("tempdir");
        let digest = OpenRouterException::compute_digest(
            OpenRouterExceptionScope::OpencodeFallback,
            "r",
            "a",
        )
        .unwrap();
        let tampered = serde_json::json!({
            "scope": "any",
            "reason": "r",
            "approved_by": "a",
            "digest": digest,
        });
        let path: PathBuf = dir.path().join("tampered.json");
        fs::write(&path, serde_json::to_string(&tampered).unwrap()).unwrap();

        let err = OpenRouterException::load(&path).unwrap_err();
        assert!(
            err.chain()
                .any(|cause| cause.to_string().contains("digest mismatch")),
            "widening scope without recomputing the digest must be rejected: {err:#}"
        );
    }

    #[test]
    fn exception_load_accepts_a_correctly_digested_record() {
        let dir = tempfile::tempdir().expect("tempdir");
        let digest = OpenRouterException::compute_digest(
            OpenRouterExceptionScope::Any,
            "reason",
            "reviewer",
        )
        .unwrap();
        let record = OpenRouterException {
            scope: OpenRouterExceptionScope::Any,
            reason: "reason".to_string(),
            approved_by: "reviewer".to_string(),
            digest,
        };
        let path: PathBuf = dir.path().join("valid.json");
        fs::write(&path, serde_json::to_string(&record).unwrap()).unwrap();

        let loaded = OpenRouterException::load(&path).expect("valid record loads");
        assert_eq!(loaded, record);
    }

    #[test]
    fn exception_load_rejects_a_missing_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("does-not-exist.json");
        let err = OpenRouterException::load(&path).unwrap_err();
        assert!(err.to_string().contains("read OpenRouter exception file"));
    }
}
