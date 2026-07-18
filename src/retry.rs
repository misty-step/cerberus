//! Bounded, family-aware transient retry (Phase 1d, backlog 052).
//!
//! docs/plans/productization-2026-07-17.md Phase 1 calls for "one global
//! workflow semaphore, bounded child concurrency, and one transient retry"
//! and separately requires "at least two model families; forbid fallback
//! that collapses independence." Those two constraints interact: once real
//! multi-seat execution exists (backlog 049/050), a naive retry-on-failure
//! could silently paper over a failed seat by re-running it against the
//! *same* provider/model family another seat already used, which would
//! quietly collapse the two-family independence the admission layer is
//! supposed to guarantee.
//!
//! This module is the general-purpose primitive that makes that collapse
//! structurally hard to do by accident: [`retry_once`] never retries more
//! than once (bounded, not unbounded backoff), and when the caller asserts
//! family diversity matters it refuses to even attempt a retry whose family
//! matches the first attempt's — no real seat-execution wiring exists yet
//! (that lands with backlog 049/050), so this is proven here with synthetic
//! family ids via fixtures/unit tests, not wired into
//! [`crate::kernel::ReviewKernel::review`].

use std::fmt;

use thiserror::Error;

/// Which call of the bounded retry loop this is. Passed to both the
/// family-selection and the work closures so a caller can vary behavior
/// (e.g. log differently) without the wrapper needing to know why.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetryAttempt {
    First,
    Retry,
}

#[derive(Debug, Error)]
pub enum RetryError<E: fmt::Debug + fmt::Display> {
    /// The retry attempt would reuse the exact same provider/model family as
    /// the first attempt while the caller asserted family diversity matters.
    /// Refused before the retry's work closure ever runs, so a caller cannot
    /// silently collapse required cross-family independence into a single
    /// family by retrying into it.
    #[error(
        "refusing retry: it would reuse family {family:?}, the same family the first attempt used, which would collapse required family diversity"
    )]
    FamilyCollapse { family: String },
    /// Both the first attempt and the one bounded retry failed.
    #[error("bounded retry exhausted after one retry (first attempt: {first}; retry: {retry})")]
    Exhausted { first: E, retry: E },
}

/// Run `work` once; if it fails, run it exactly one more time (a single
/// bounded transient retry — never unbounded backoff, never a second retry).
///
/// `family_for` is called before each attempt's `work` closure to decide
/// (side-effect-free) which provider/model family that attempt targets, and
/// `work` performs the actual attempt for a given family. When
/// `require_family_diversity` is set, the retry's family is compared
/// against the first attempt's family *before* `work` runs for the retry —
/// if they match, [`RetryError::FamilyCollapse`] is returned immediately
/// and the retry's `work` closure is never invoked (no silent retry, and no
/// wasted/side-effecting attempt into a family that would defeat the point
/// of retrying).
pub fn retry_once<T, E>(
    require_family_diversity: bool,
    mut family_for: impl FnMut(RetryAttempt) -> String,
    mut work: impl FnMut(RetryAttempt, &str) -> Result<T, E>,
) -> Result<T, RetryError<E>>
where
    E: fmt::Debug + fmt::Display,
{
    let first_family = family_for(RetryAttempt::First);
    match work(RetryAttempt::First, &first_family) {
        Ok(value) => Ok(value),
        Err(first_err) => {
            let retry_family = family_for(RetryAttempt::Retry);
            if require_family_diversity && retry_family == first_family {
                return Err(RetryError::FamilyCollapse {
                    family: retry_family,
                });
            }
            match work(RetryAttempt::Retry, &retry_family) {
                Ok(value) => Ok(value),
                Err(retry_err) => Err(RetryError::Exhausted {
                    first: first_err,
                    retry: retry_err,
                }),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;

    use super::*;

    #[test]
    fn succeeds_without_retry_when_first_attempt_succeeds() {
        let calls = RefCell::new(0);
        let result = retry_once::<_, String>(
            true,
            |_attempt| "family-a".to_string(),
            |_attempt, family| {
                *calls.borrow_mut() += 1;
                Ok(format!("ok:{family}"))
            },
        );
        assert_eq!(result.unwrap(), "ok:family-a");
        assert_eq!(*calls.borrow(), 1, "no retry should have run");
    }

    #[test]
    fn retries_exactly_once_then_gives_up() {
        let calls = RefCell::new(0);
        let result = retry_once::<(), String>(
            false,
            |_attempt| "family-a".to_string(),
            |_attempt, _family| {
                *calls.borrow_mut() += 1;
                Err(format!("transient failure #{}", calls.borrow()))
            },
        );
        assert_eq!(
            *calls.borrow(),
            2,
            "exactly one retry: first attempt plus one bounded retry, never more"
        );
        match result {
            Err(RetryError::Exhausted { first, retry }) => {
                assert_eq!(first, "transient failure #1");
                assert_eq!(retry, "transient failure #2");
            }
            other => panic!("expected Exhausted, got {other:?}"),
        }
    }

    #[test]
    fn retry_into_same_family_is_refused_when_diversity_required() {
        let work_calls = RefCell::new(0);
        let result = retry_once::<(), String>(
            true,
            |_attempt| "family-a".to_string(),
            |attempt, _family| {
                *work_calls.borrow_mut() += 1;
                match attempt {
                    RetryAttempt::First => Err("transient failure".to_string()),
                    RetryAttempt::Retry => Ok(()),
                }
            },
        );
        match result {
            Err(RetryError::FamilyCollapse { family }) => assert_eq!(family, "family-a"),
            other => panic!("expected FamilyCollapse, got {other:?}"),
        }
        assert_eq!(
            *work_calls.borrow(),
            1,
            "the retry's work closure must never run once family collapse is detected"
        );
    }

    #[test]
    fn retry_into_a_different_family_is_allowed_when_diversity_required() {
        let result = retry_once::<_, String>(
            true,
            |attempt| match attempt {
                RetryAttempt::First => "family-a".to_string(),
                RetryAttempt::Retry => "family-b".to_string(),
            },
            |attempt, family| match attempt {
                RetryAttempt::First => Err("transient failure".to_string()),
                RetryAttempt::Retry => Ok(family.to_string()),
            },
        );
        assert_eq!(result.unwrap(), "family-b");
    }

    #[test]
    fn same_family_retry_is_allowed_when_diversity_not_required() {
        // When the caller hasn't asserted family diversity matters (e.g. a
        // single-seat run with no cross-family requirement), retrying into
        // the same family is an ordinary retry, not a collapse.
        let result = retry_once::<_, String>(
            false,
            |_attempt| "family-a".to_string(),
            |attempt, family| match attempt {
                RetryAttempt::First => Err("transient failure".to_string()),
                RetryAttempt::Retry => Ok(family.to_string()),
            },
        );
        assert_eq!(result.unwrap(), "family-a");
    }
}
