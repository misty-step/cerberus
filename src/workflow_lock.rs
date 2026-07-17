//! Global review-workflow semaphore (Phase 1d, backlog 052).
//!
//! Cerberus is a stateless CLI: cron, launchd, a webhook responder, CI, or
//! another plane can all invoke it concurrently on the same host, and
//! nothing in-process stops two invocations from racing each other through
//! the same substrate, credential-minting, or receipt-writing paths. This
//! module gives every invocation of [`crate::kernel::ReviewKernel::review`]
//! a single, host-wide mutual-exclusion point: an exclusive, non-blocking
//! advisory lock (`flock(2)`) on a well-known file. "Non-blocking" is
//! deliberate — a caller that loses the race gets a fast, typed
//! [`WorkflowLockError::Contended`] instead of hanging behind an unbounded
//! wait, matching the "bounded" requirement from
//! docs/plans/productization-2026-07-17.md Phase 1.
//!
//! Crash safety mirrors [`crate::openrouter_keys::ScopedKeyGuard`] and
//! [`crate::container`]'s `EgressProxyGuard`: the lock is released by an
//! RAII guard's `Drop` (best effort, logged, never panics) the moment the
//! guard goes out of scope — including on early return via `?` or an
//! unwinding panic. Unlike those two, there is no orphan sweep needed here:
//! `flock` locks are owned by the kernel per open file description, so a
//! `SIGKILL`ed process releases the lock automatically when its file
//! descriptors are torn down, without any cooperating cleanup step.
//!
//! The lock file itself lives under the OS temp directory rather than a
//! `cwd`-relative path like `config/omp-version.json` (see
//! [`crate::harness::omp`]'s `OMP_PIN_PATH`): callers can invoke `cerberus`
//! from different working directories, so a path relative to the process's
//! current directory would not actually be global across those callers. The
//! temp directory is the one location every invocation on the same host
//! agrees on without configuration.

use std::fs::{self, File, OpenOptions};
use std::io;
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};

use thiserror::Error;

/// Env var that overrides the default lock file path. Production code never
/// needs this; it exists so tests (and, if ever needed, an operator running
/// multiple independent Cerberus deployments on one host) can point separate
/// invocations at separate lock files instead of contending on the same
/// well-known path.
pub const WORKFLOW_LOCK_PATH_ENV: &str = "CERBERUS_WORKFLOW_LOCK_PATH";

/// Fixed lock file name under the OS temp directory. See the module doc
/// comment for why a temp-dir path was chosen over a `cwd`-relative one.
const WORKFLOW_LOCK_FILE_NAME: &str = "cerberus-review-workflow.lock";

/// A held global review-workflow lock. Dropping this releases the lock.
#[derive(Debug)]
pub struct WorkflowLockGuard {
    file: File,
    path: PathBuf,
}

#[derive(Debug, Error)]
pub enum WorkflowLockError {
    /// Another process already holds the lock. Distinct from
    /// [`WorkflowLockError::Io`] so a caller (or an operator reading the
    /// error) can tell "someone else is running a review right now" apart
    /// from "the lock file itself is unusable" at a glance, rather than both
    /// surfacing as an indistinguishable generic `anyhow` string.
    #[error(
        "another cerberus review workflow is already running (lock held at {path});          only one global review workflow may run at a time"
    )]
    Contended { path: String },
    /// The lock file could not be created, opened, or locked for a reason
    /// other than contention (permissions, missing parent directory, etc.).
    #[error("failed to acquire workflow lock at {path}: {source}")]
    Io { path: String, source: io::Error },
}

/// The well-known lock file path every `cerberus` invocation on this host
/// agrees on, unless overridden by `CERBERUS_WORKFLOW_LOCK_PATH` (tests use
/// the override so parallel test runs don't contend with each other or with
/// a real review running on the same machine).
pub fn default_workflow_lock_path() -> PathBuf {
    if let Ok(path) = std::env::var(WORKFLOW_LOCK_PATH_ENV) {
        return PathBuf::from(path);
    }
    std::env::temp_dir().join(WORKFLOW_LOCK_FILE_NAME)
}

/// Acquire the global review-workflow semaphore at `path`. Non-blocking: if
/// another process already holds it, this returns
/// `Err(WorkflowLockError::Contended)` immediately rather than waiting.
pub fn acquire_workflow_lock(path: &Path) -> Result<WorkflowLockGuard, WorkflowLockError> {
    let display_path = path.display().to_string();
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent).map_err(|source| WorkflowLockError::Io {
            path: display_path.clone(),
            source,
        })?;
    }
    let file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(path)
        .map_err(|source| WorkflowLockError::Io {
            path: display_path.clone(),
            source,
        })?;

    // SAFETY: `file`'s fd is open and owned by this stack frame for the
    // duration of the call; `flock` only mutates kernel-side lock state
    // keyed by the open file description, not the memory `file` points at.
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc != 0 {
        let err = io::Error::last_os_error();
        let contended = err.kind() == io::ErrorKind::WouldBlock
            || err.raw_os_error() == Some(libc::EWOULDBLOCK)
            || err.raw_os_error() == Some(libc::EAGAIN);
        return Err(if contended {
            WorkflowLockError::Contended { path: display_path }
        } else {
            WorkflowLockError::Io {
                path: display_path,
                source: err,
            }
        });
    }

    Ok(WorkflowLockGuard {
        file,
        path: path.to_path_buf(),
    })
}

impl Drop for WorkflowLockGuard {
    fn drop(&mut self) {
        // SAFETY: `self.file`'s fd is still open (it only closes after this
        // call, as part of the same drop). Unlocking before close is
        // belt-and-suspenders documentation of intent; the OS would release
        // the lock on close (or process exit, including SIGKILL) regardless.
        let rc = unsafe { libc::flock(self.file.as_raw_fd(), libc::LOCK_UN) };
        if rc != 0 {
            let err = io::Error::last_os_error();
            eprintln!(
                "cerberus: failed to release workflow lock {}: {err}; the OS releases it when \
                 this process's file descriptors close regardless",
                self.path.display()
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch_lock_path(tag: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "cerberus-workflow-lock-test-{tag}-{}.lock",
            std::process::id()
        ))
    }

    #[test]
    fn acquires_and_releases_lock_file() {
        let path = scratch_lock_path("basic");
        let _ = fs::remove_file(&path);

        let guard = acquire_workflow_lock(&path).expect("first acquire succeeds");
        drop(guard);

        // Once dropped, a fresh acquire succeeds again — proves release
        // actually happened rather than leaking the lock.
        let guard = acquire_workflow_lock(&path).expect("second acquire succeeds after release");
        drop(guard);
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn contended_lock_fails_fast_with_distinct_error() {
        let path = scratch_lock_path("contended");
        let _ = fs::remove_file(&path);

        let _held = acquire_workflow_lock(&path).expect("first acquire holds the lock");
        let second = acquire_workflow_lock(&path);

        match second {
            Err(WorkflowLockError::Contended { path: reported }) => {
                assert_eq!(reported, path.display().to_string());
            }
            other => panic!("expected Contended, got {other:?}"),
        }

        let _ = fs::remove_file(&path);
    }

    #[test]
    fn contended_error_message_is_distinct_from_generic_io_failure() {
        let path = scratch_lock_path("message");
        let _ = fs::remove_file(&path);

        let _held = acquire_workflow_lock(&path).expect("first acquire holds the lock");
        let err = acquire_workflow_lock(&path).unwrap_err();
        let message = err.to_string();
        assert!(
            message.contains("already running") && message.contains("one global review workflow"),
            "contention message should name itself distinctly, got: {message}"
        );

        let _ = fs::remove_file(&path);
    }

    #[test]
    fn missing_parent_directory_is_created() {
        let base = std::env::temp_dir().join(format!(
            "cerberus-workflow-lock-test-nested-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&base);
        let path = base.join("nested/lock/dir/review.lock");

        let guard = acquire_workflow_lock(&path).expect("creates missing parent directories");
        drop(guard);

        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn default_path_honors_env_override() {
        let override_path = scratch_lock_path("override");
        // SAFETY: test-only env mutation; cargo test runs this crate's unit
        // tests in threads but each test uses a uniquely-named lock path, so
        // races over the env var's *value* don't cause false lock contention
        // even if two tests observe interleaved env state momentarily.
        unsafe {
            std::env::set_var(WORKFLOW_LOCK_PATH_ENV, &override_path);
        }
        let resolved = default_workflow_lock_path();
        unsafe {
            std::env::remove_var(WORKFLOW_LOCK_PATH_ENV);
        }
        assert_eq!(resolved, override_path);
    }
}
