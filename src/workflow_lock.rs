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
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
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
        "another cerberus review workflow is already running (lock held at {path}); only one global review workflow may run at a time"
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
    resolve_workflow_lock_path(std::env::var(WORKFLOW_LOCK_PATH_ENV).ok())
}

/// Pure path-resolution logic behind [`default_workflow_lock_path`], split
/// out so tests can exercise the override/default branches by passing a
/// value directly instead of mutating the process-wide `std::env` — the
/// lib unit test binary runs every `#[test]` in its own thread of one
/// shared process, and `std::env::set_var`/`remove_var` are `unsafe`
/// specifically because they race with any concurrent env read on another
/// thread (this function's own callers included); a pure function has no
/// such hazard to reason about, so it is preferred over a "no other test
/// touches this today" argument that a future test could quietly violate.
fn resolve_workflow_lock_path(override_value: Option<String>) -> PathBuf {
    match override_value {
        Some(path) => PathBuf::from(path),
        None => std::env::temp_dir().join(WORKFLOW_LOCK_FILE_NAME),
    }
}

/// Open `path` as the shared lock file, safe against another local user
/// pre-planting a symlink at this predictable, well-known path inside a
/// shared, world-writable temp directory (the classic `/tmp` race: a
/// naive `open(create=true) + chmod(path)` would follow an attacker's
/// symlink and re-permission whatever it points at).
///
/// - If nothing exists at `path` yet, `O_CREAT | O_EXCL` atomically creates
///   a fresh regular file — this refuses to follow or overwrite anything
///   already there, including a symlink, so success here proves we hold a
///   brand new inode no one else could have redirected. `fchmod` on that
///   already-open fd (not the path) then safely makes it host-wide
///   shared, matching this module's "host-wide" contract without any
///   path-based re-resolution a symlink swap could hijack. A chmod
///   failure is propagated (and the unusable file removed) rather than
///   silently left at a restrictive, umask-derived mode — that would
///   quietly recreate the exact cross-user failure this function exists
///   to prevent, and a caller can't act on a problem it never sees.
/// - If it already exists, reopen with `O_NOFOLLOW` (fails on a symlink
///   instead of following it) and verify the fd is a plain regular file
///   before trusting it as the lock. No chmod in this branch: only the
///   owner can chmod, and whoever created it already had to leave it
///   shared for this `open` to succeed at all.
/// - A microsecond race is possible: another process's `create_new` above
///   can succeed while its `fchmod` to 0o666 hasn't run yet, so a
///   concurrent reopen here can transiently see the restrictive
///   umask-derived mode and fail with `PermissionDenied` even though the
///   file is about to become shared. Retry the reopen briefly rather than
///   surfacing that as a permanent error.
/// - The reopen also sets `O_NONBLOCK`: opening a FIFO for writing
///   without it blocks the calling thread until some other process opens
///   the same path for reading — indefinitely, if no one ever does. A
///   planted FIFO at this well-known path would silently turn the "never
///   waits" contract this whole module promises into a hang, and the
///   is-a-regular-file check below never even gets a chance to run.
///   `O_NONBLOCK` is a no-op on a regular file (the only thing we want to
///   accept), so this costs nothing on the legitimate path.
fn open_shared_lock_file(path: &Path) -> io::Result<File> {
    const MAX_REOPEN_RETRIES: u32 = 5;
    let mut retries = 0;
    loop {
        match OpenOptions::new().create_new(true).write(true).open(path) {
            Ok(file) => {
                if let Err(e) = file.set_permissions(fs::Permissions::from_mode(0o666)) {
                    drop(file);
                    let _ = fs::remove_file(path);
                    return Err(e);
                }
                return Ok(file);
            }
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                match OpenOptions::new()
                    .write(true)
                    .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
                    .open(path)
                {
                    Ok(file) => {
                        if !file.metadata()?.is_file() {
                            return Err(io::Error::other(format!(
                                "refusing non-regular-file lock path {} (symlink or special file?)",
                                path.display()
                            )));
                        }
                        return Ok(file);
                    }
                    Err(reopen_err)
                        if reopen_err.kind() == io::ErrorKind::PermissionDenied
                            && retries < MAX_REOPEN_RETRIES =>
                    {
                        retries += 1;
                        std::thread::sleep(std::time::Duration::from_millis(2));
                    }
                    Err(reopen_err) => return Err(reopen_err),
                }
            }
            Err(e) => return Err(e),
        }
    }
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
    let file = open_shared_lock_file(path).map_err(|source| WorkflowLockError::Io {
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
    use std::os::unix::ffi::OsStrExt;

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
    fn resolve_path_prefers_override_over_default() {
        let override_path = scratch_lock_path("override");
        let resolved = resolve_workflow_lock_path(Some(override_path.display().to_string()));
        assert_eq!(resolved, override_path);
    }

    #[test]
    fn resolve_path_falls_back_to_temp_dir_default_without_override() {
        let resolved = resolve_workflow_lock_path(None);
        assert_eq!(resolved, std::env::temp_dir().join(WORKFLOW_LOCK_FILE_NAME));
    }

    #[test]
    fn freshly_created_lock_file_is_shared_mode_for_every_os_user() {
        let path = scratch_lock_path("shared-mode");
        let _ = fs::remove_file(&path);

        let guard = acquire_workflow_lock(&path).expect("first acquire creates the lock file");
        let mode = fs::metadata(&path)
            .expect("lock file exists")
            .permissions()
            .mode();
        drop(guard);
        let _ = fs::remove_file(&path);

        assert_eq!(
            mode & 0o777,
            0o666,
            "a freshly created lock file must be rw for every OS user so a different \
             OS user's `cerberus` invocation (CI runner, Bitterblossom service account, \
             ...) can still open and flock it under the default umask"
        );
    }

    #[test]
    fn refuses_a_symlink_planted_at_the_lock_path() {
        // Simulates the classic shared-`/tmp` attack: another local user
        // (or a race) plants a symlink at the well-known lock path before
        // Cerberus gets there, hoping a naive "open + chmod" follows it
        // and re-permissions or corrupts whatever it points at.
        let path = scratch_lock_path("symlink-attack");
        let target = scratch_lock_path("symlink-attack-target");
        let _ = fs::remove_file(&path);
        let _ = fs::remove_file(&target);
        fs::write(&target, b"not a lock file").expect("create symlink target");
        // Pin an exact starting mode (independent of this process's umask)
        // so the after-assertion below proves the target was genuinely
        // untouched, not merely "not already 0o666 by chance".
        fs::set_permissions(&target, fs::Permissions::from_mode(0o600))
            .expect("pin target to a known starting mode");
        std::os::unix::fs::symlink(&target, &path).expect("plant symlink at the lock path");

        let result = acquire_workflow_lock(&path);

        let target_content_after = fs::read(&target).expect("target still exists");
        let target_mode_after = fs::metadata(&target)
            .expect("target still exists")
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(
            target_mode_after, 0o600,
            "must never chmod through a symlink onto the attacker's target file"
        );
        assert_eq!(
            target_content_after, b"not a lock file",
            "must never write through a symlink onto the attacker's target file"
        );
        match result {
            Err(WorkflowLockError::Io { .. }) => {}
            other => panic!("expected a refused Io error for a symlinked lock path, got {other:?}"),
        }

        let _ = fs::remove_file(&path);
        let _ = fs::remove_file(&target);
    }

    #[test]
    fn refuses_a_fifo_planted_at_the_lock_path_without_blocking() {
        // A FIFO opened for writing without `O_NONBLOCK` blocks until some
        // other process opens it for reading — which, for a lock path no
        // legitimate reader ever opens, means forever. Run the acquire
        // call on a background thread and bound the wait with
        // `recv_timeout` instead of calling it inline: a regression here
        // would otherwise hang this test (and this whole test binary)
        // forever rather than failing, leaving only the outer CI timeout
        // to notice — not a real oracle.
        let path = scratch_lock_path("fifo-attack");
        let _ = fs::remove_file(&path);
        let c_path = std::ffi::CString::new(path.as_os_str().as_bytes()).expect("no NUL bytes");
        let rc = unsafe { libc::mkfifo(c_path.as_ptr(), 0o600) };
        assert_eq!(
            rc,
            0,
            "failed to create test fifo: {}",
            io::Error::last_os_error()
        );

        let (tx, rx) = std::sync::mpsc::channel();
        let thread_path = path.clone();
        let handle = std::thread::spawn(move || {
            let _ = tx.send(acquire_workflow_lock(&thread_path));
        });

        let result = match rx.recv_timeout(std::time::Duration::from_secs(2)) {
            Ok(result) => result,
            Err(_) => {
                // Regressed: the background thread is stuck inside a
                // blocking write-open on the fifo. Open the read side to
                // rendezvous and unblock it (a fifo write-open blocks
                // specifically until a reader shows up) so the thread can
                // finish and be joined instead of leaking permanently
                // blocked, then fail with a clear message.
                let _ = fs::File::open(&path);
                let _ = handle.join();
                let _ = fs::remove_file(&path);
                panic!(
                    "acquire_workflow_lock blocked for over 2s on a planted fifo instead of \
                     failing fast — the non-blocking contract regressed"
                );
            }
        };
        let _ = handle.join();

        match result {
            Err(WorkflowLockError::Io { .. }) => {}
            other => panic!("expected a refused Io error for a fifo lock path, got {other:?}"),
        }

        let _ = fs::remove_file(&path);
    }
}
