//! Container-isolated review substrate (backlog 013 M2, slice 1).
//!
//! Where [`crate::openrouter_keys`] made a stolen model credential worthless,
//! this module contains the *other* damage an untrusted-PR review agent could
//! do with webfetch/bash access: reaching a non-model host, trashing files
//! outside its workspace, or reading the host git object store through a
//! worktree's `.git` handle.
//!
//! `run_container_substrate` never mounts the caller's real checkout. It
//! extracts a `.git`-less copy via `git archive` into a disposable temp root,
//! mounts *only* that root (plus the substrate binary, read-only) into a
//! Docker container, and runs the whole thing with `--network none`: this
//! slice denies all egress, including to the model API, which is strictly
//! stronger than "non-model egress blocked" and needs no allowlist to get
//! right. Carving a narrow model-API-only exception is tracked as a follow-up
//! slice, not built here.

use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use anyhow::{anyhow, Context, Result};
use uuid::Uuid;

use crate::digest::request_digest;
use crate::harness::{
    read_artifact_file, set_private_directory_permissions, set_private_permissions, ExecutionPlan,
    HarnessRun, ARTIFACT_FILENAME,
};
use crate::prompt::build_opencode_message;
use crate::schema::{ContextCapabilities, ReviewRequest, ReviewTelemetry};

/// No image is built or published for this substrate; it runs the mounted
/// substrate binary inside a stock, widely-mirrored base image. `bookworm`
/// ships bash, which the fixture/red-team substrate scripts use.
pub const DEFAULT_CONTAINER_IMAGE: &str = "debian:bookworm-slim";

/// Where the disposable host root (archived workspace + request/prompt files)
/// is mounted inside the container. Fixed and unconfigurable: every path the
/// agent is told about is relative to this, so there is exactly one place to
/// audit for host-path leakage.
const CONTAINER_MOUNT_ROOT: &str = "/cerberus";
const CONTAINER_BINARY_PATH: &str = "/usr/local/bin/cerberus-substrate";
const CONTAINER_NAME_PREFIX: &str = "cerberus-review-";

#[derive(Debug, Clone)]
pub struct ContainerOpencodeSubstrateConfig {
    /// `docker` (or a compatible CLI) resolved from the trusted search path,
    /// same as any other substrate binary.
    pub docker_binary: String,
    /// Base image `docker run` starts from. See [`DEFAULT_CONTAINER_IMAGE`].
    pub image: String,
    /// Host path to the substrate executable (real `opencode`, or a
    /// fixture/red-team script) that gets bind-mounted read-only and exec'd
    /// inside the container in place of a real `docker build`.
    pub binary_host_path: PathBuf,
    /// Parent directory the disposable per-run host root is created under.
    /// `None` uses the OS temp dir, which is correct wherever the Docker
    /// daemon shares the host filesystem directly (native Linux, Docker
    /// Desktop's default sharing). Docker contexts that run inside a VM with
    /// a narrower mount allowlist (e.g. colima's default, which mounts only
    /// `$HOME`) need this pointed at a location the daemon can actually see —
    /// otherwise `-v` mounts silently resolve to empty directories inside the
    /// container instead of failing loudly.
    pub host_root_parent: Option<PathBuf>,
}

pub(crate) fn run_container_substrate(
    request: &ReviewRequest,
    timeout: Duration,
    config: &ContainerOpencodeSubstrateConfig,
) -> Result<HarnessRun> {
    let request_digest = request_digest(request)?;
    let capabilities = ContextCapabilities::from_request(request);

    let mut builder = tempfile::Builder::new();
    builder.prefix("cerberus-container-");
    let temp = match &config.host_root_parent {
        Some(parent) => {
            fs::create_dir_all(parent).with_context(|| {
                format!("create container host root parent {}", parent.display())
            })?;
            builder.tempdir_in(parent)
        }
        None => builder.tempdir(),
    }
    .context("create private container host root")?;
    let host_root = temp.path();
    set_private_directory_permissions(host_root)?;

    let workspace = prepare_archive_workspace(request, host_root)?;
    let container_workspace = container_path(&workspace.workspace_rel);
    let out_path_container = container_workspace.join(ARTIFACT_FILENAME);
    let out_path_host = host_root
        .join(&workspace.workspace_rel)
        .join(ARTIFACT_FILENAME);

    let child_request = request_with_container_paths(request, &workspace);
    let request_path_host = host_root.join("review-request.json");
    fs::write(
        &request_path_host,
        serde_json::to_vec_pretty(&child_request)?,
    )
    .context("write container review request")?;
    set_private_permissions(&request_path_host)?;
    let request_path_container = container_path(Path::new("review-request.json"));

    let message = build_opencode_message(
        &child_request,
        &capabilities,
        &request_digest,
        &out_path_container,
    )
    .context("build container substrate message")?;

    let container_args = vec![
        "run".to_string(),
        message,
        "--format".to_string(),
        "json".to_string(),
        "--dir".to_string(),
        container_workspace.display().to_string(),
        "--file".to_string(),
        request_path_container.display().to_string(),
    ];

    let container_name = format!("{CONTAINER_NAME_PREFIX}{}", Uuid::new_v4());
    let docker_args = docker_run_args(&container_name, host_root, config, &container_args);

    let plan = ExecutionPlan {
        harness: "container-opencode".to_string(),
        command: config.docker_binary.clone(),
        args: docker_args.clone(),
        cwd: host_root.display().to_string(),
        timeout_ms: timeout.as_millis() as u64,
        env_allowlist: Vec::new(),
        context_capabilities: capabilities,
        prompt_transport: "container argv instructions plus mounted request file".to_string(),
        private_material_in_argv: false,
        workspace_mode: workspace.mode.to_string(),
        runtime_transcripts: Vec::new(),
    };

    let mut command = Command::new(&config.docker_binary);
    command.args(&docker_args).stdin(Stdio::null());
    let output = run_docker_with_timeout(command, &container_name, &config.docker_binary, timeout)?;

    let transcript = format!(
        "[container-opencode]\nname: {container_name}\nexit_status: {}\nelapsed_ms: {}\n\n[stdout]\n{}\n\n[stderr]\n{}\n",
        output.status,
        output.elapsed_ms,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );

    let artifact = read_artifact_file(&out_path_host)?;

    Ok(HarnessRun {
        artifact,
        transcript,
        execution_plan: plan,
        telemetry: ReviewTelemetry::default(),
    })
}

fn docker_run_args(
    container_name: &str,
    host_root: &Path,
    config: &ContainerOpencodeSubstrateConfig,
    container_args: &[String],
) -> Vec<String> {
    let mut args: Vec<String> = vec![
        "run".to_string(),
        "--rm".to_string(),
        "--name".to_string(),
        container_name.to_string(),
        // Slice 1: deny ALL egress, including to the model API. Strictly
        // stronger than "non-model egress blocked" and needs no allowlist to
        // get right. A narrow model-only exception is a follow-up slice.
        "--network".to_string(),
        "none".to_string(),
        "--read-only".to_string(),
        "--tmpfs".to_string(),
        "/tmp:rw,size=64m".to_string(),
        "--cap-drop".to_string(),
        "ALL".to_string(),
        "--security-opt".to_string(),
        "no-new-privileges".to_string(),
        "--pids-limit".to_string(),
        "256".to_string(),
        "-v".to_string(),
        format!("{}:{CONTAINER_MOUNT_ROOT}:rw", host_root.display()),
        "-v".to_string(),
        format!(
            "{}:{CONTAINER_BINARY_PATH}:ro",
            config.binary_host_path.display()
        ),
        "--entrypoint".to_string(),
        CONTAINER_BINARY_PATH.to_string(),
        config.image.clone(),
    ];
    args.extend(container_args.iter().cloned());
    args
}

struct DockerOutput {
    status: String,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    elapsed_ms: u128,
}

/// Like the local harness's `run_with_timeout`, but a timeout here must also
/// `docker kill` the named container: killing the `docker run` CLIENT process
/// does not stop the container, which dockerd keeps running server-side.
fn run_docker_with_timeout(
    mut command: Command,
    container_name: &str,
    docker_binary: &str,
    timeout: Duration,
) -> Result<DockerOutput> {
    let stdout_capture = tempfile::NamedTempFile::new().context("create docker stdout capture")?;
    let stderr_capture = tempfile::NamedTempFile::new().context("create docker stderr capture")?;
    command.stdout(Stdio::from(
        stdout_capture
            .reopen()
            .context("open docker stdout writer")?,
    ));
    command.stderr(Stdio::from(
        stderr_capture
            .reopen()
            .context("open docker stderr writer")?,
    ));
    let start = Instant::now();
    let mut child = command.spawn().context("spawn docker run")?;
    loop {
        if let Some(status) = child.try_wait().context("poll docker run")? {
            return Ok(DockerOutput {
                status: status.to_string(),
                stdout: read_capture(stdout_capture.path())?,
                stderr: read_capture(stderr_capture.path())?,
                elapsed_ms: start.elapsed().as_millis(),
            });
        }
        if start.elapsed() >= timeout {
            let _ = Command::new(docker_binary)
                .args(["kill", container_name])
                .output();
            let _ = child.wait();
            return Ok(DockerOutput {
                status: "timeout".to_string(),
                stdout: read_capture(stdout_capture.path())?,
                stderr: read_capture(stderr_capture.path())?,
                elapsed_ms: start.elapsed().as_millis(),
            });
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

fn read_capture(path: &Path) -> Result<Vec<u8>> {
    let mut file = fs::File::open(path)?;
    file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;
    Ok(bytes)
}

/// A disposable, `.git`-less workspace built via `git archive`, plus the
/// relative paths (within `host_root`) that make it up.
struct ArchiveWorkspace {
    workspace_rel: PathBuf,
    base_rel: Option<PathBuf>,
    mode: &'static str,
}

fn prepare_archive_workspace(
    request: &ReviewRequest,
    host_root: &Path,
) -> Result<ArchiveWorkspace> {
    if let Some(head) = &request.context.workspaces.head {
        let head_sha = head.sha.as_deref().ok_or_else(|| {
            anyhow!(
                "repo_head workspace {} requires a sha for disposable container review",
                head.path
            )
        })?;
        let head_rel = PathBuf::from("workspace/repo-head");
        git_archive_extract(Path::new(&head.path), head_sha, &host_root.join(&head_rel))?;

        let base_rel = request
            .context
            .workspaces
            .base
            .as_ref()
            .map(|base| -> Result<PathBuf> {
                let base_sha = base.sha.as_deref().ok_or_else(|| {
                    anyhow!(
                        "repo_base workspace {} requires a sha for disposable container review",
                        base.path
                    )
                })?;
                let rel = PathBuf::from("workspace/repo-base");
                git_archive_extract(Path::new(&base.path), base_sha, &host_root.join(&rel))?;
                Ok(rel)
            })
            .transpose()?;

        let mode = if base_rel.is_some() {
            "container_archive_base_head"
        } else {
            "container_archive_head"
        };
        Ok(ArchiveWorkspace {
            workspace_rel: head_rel,
            base_rel,
            mode,
        })
    } else {
        let rel = PathBuf::from("workspace/packet");
        let dir = host_root.join(&rel);
        fs::create_dir_all(&dir).context("create diff-only container packet workspace")?;
        let request_path = dir.join("request.json");
        fs::write(&request_path, serde_json::to_vec_pretty(request)?)
            .context("write container packet request")?;
        let diff_path = dir.join("change.diff");
        fs::write(&diff_path, request.change.diff.body.as_bytes())
            .context("write container packet diff")?;
        set_private_permissions(&request_path)?;
        set_private_permissions(&diff_path)?;
        Ok(ArchiveWorkspace {
            workspace_rel: rel,
            base_rel: None,
            mode: "container_diff_packet",
        })
    }
}

/// `git archive <sha> | tar -x -C <dest>` — a content-only extraction with no
/// `.git` directory, so the mounted tree carries no handle back to the host
/// repository's object store (unlike `git worktree add`, whose `.git` file
/// points straight at it).
fn git_archive_extract(source: &Path, sha: &str, dest: &Path) -> Result<()> {
    fs::create_dir_all(dest)
        .with_context(|| format!("create archive destination {}", dest.display()))?;
    let mut git = Command::new("git")
        .arg("-C")
        .arg(source)
        .args(["archive", "--format=tar"])
        .arg(sha)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("spawn git archive {sha} from {}", source.display()))?;
    let git_stdout = git
        .stdout
        .take()
        .ok_or_else(|| anyhow!("git archive produced no stdout pipe"))?;
    let tar_status = Command::new("tar")
        .args(["-x", "-C"])
        .arg(dest)
        .stdin(Stdio::from(git_stdout))
        .stderr(Stdio::piped())
        .status()
        .with_context(|| format!("run tar extraction into {}", dest.display()))?;
    let git_output = git
        .wait_with_output()
        .with_context(|| format!("wait for git archive {sha}"))?;
    if !git_output.status.success() {
        return Err(anyhow!(
            "git archive {sha} from {} failed: {}",
            source.display(),
            String::from_utf8_lossy(&git_output.stderr)
        ));
    }
    if !tar_status.success() {
        return Err(anyhow!(
            "tar extraction into {} failed with status {tar_status}",
            dest.display()
        ));
    }
    Ok(())
}

fn container_path(relative: &Path) -> PathBuf {
    Path::new(CONTAINER_MOUNT_ROOT).join(relative)
}

/// The request the agent actually reads: workspace paths rewritten to their
/// container-internal mount points. The real host checkout path never
/// appears anywhere the agent can see.
fn request_with_container_paths(
    request: &ReviewRequest,
    workspace: &ArchiveWorkspace,
) -> ReviewRequest {
    let mut child_request = request.clone();
    if let Some(head) = &mut child_request.context.workspaces.head {
        head.path = container_path(&workspace.workspace_rel)
            .display()
            .to_string();
    }
    if let (Some(base), Some(base_rel)) = (
        &mut child_request.context.workspaces.base,
        &workspace.base_rel,
    ) {
        base.path = container_path(base_rel).display().to_string();
    }
    child_request
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::{WorkspaceKind, WorkspaceRef};
    use serde_json::json;

    fn diff_only_request() -> ReviewRequest {
        serde_json::from_value(json!({
            "schema_version": "cerberus.review_request.v1",
            "request_id": "req-container-1",
            "source": {"kind": "fixture", "metadata": {}},
            "change": {
                "title": "change",
                "diff": {"format": "unified", "body": "diff --git a/src/lib.rs b/src/lib.rs\n"},
                "files": []
            },
            "context": {},
            "policy": {}
        }))
        .unwrap()
    }

    #[test]
    fn container_path_is_rooted_under_the_fixed_mount() {
        let path = container_path(Path::new("workspace/repo-head"));
        assert_eq!(path, PathBuf::from("/cerberus/workspace/repo-head"));
    }

    #[test]
    fn diff_only_request_prepares_a_packet_workspace() {
        let request = diff_only_request();
        let temp = tempfile::tempdir().unwrap();

        let workspace = prepare_archive_workspace(&request, temp.path()).unwrap();

        assert_eq!(workspace.mode, "container_diff_packet");
        assert!(workspace.base_rel.is_none());
        assert!(temp
            .path()
            .join(&workspace.workspace_rel)
            .join("change.diff")
            .is_file());
        assert!(temp
            .path()
            .join(&workspace.workspace_rel)
            .join("request.json")
            .is_file());
    }

    #[test]
    fn git_archive_extract_produces_a_git_less_tree() {
        let repo = tempfile::tempdir().unwrap();
        run(&repo, ["git", "init", "-q"]);
        run(&repo, ["git", "config", "user.email", "test@example.com"]);
        run(&repo, ["git", "config", "user.name", "Test"]);
        fs::write(repo.path().join("hello.txt"), "hi\n").unwrap();
        run(&repo, ["git", "add", "."]);
        run(&repo, ["git", "commit", "-q", "-m", "init"]);
        let sha = output(&repo, ["git", "rev-parse", "HEAD"]);

        let dest = tempfile::tempdir().unwrap();
        git_archive_extract(repo.path(), sha.trim(), dest.path()).unwrap();

        assert!(dest.path().join("hello.txt").is_file());
        assert!(
            !dest.path().join(".git").exists(),
            "archived tree must carry no .git handle back to the host repo"
        );
    }

    #[test]
    fn request_with_container_paths_never_leaks_the_host_checkout_path() {
        let mut request = diff_only_request();
        request.context.workspaces.head = Some(WorkspaceRef {
            kind: WorkspaceKind::Checkout,
            path: "/Users/operator/very/real/host/checkout".to_string(),
            ref_name: None,
            sha: Some("deadbeef".to_string()),
        });
        let workspace = ArchiveWorkspace {
            workspace_rel: PathBuf::from("workspace/repo-head"),
            base_rel: None,
            mode: "container_archive_head",
        };

        let rewritten = request_with_container_paths(&request, &workspace);

        let head_path = rewritten.context.workspaces.head.unwrap().path;
        assert_eq!(head_path, "/cerberus/workspace/repo-head");
        assert!(!head_path.contains("/Users/operator"));
    }

    fn run<const N: usize>(dir: &tempfile::TempDir, args: [&str; N]) {
        let status = Command::new(args[0])
            .args(&args[1..])
            .current_dir(dir.path())
            .status()
            .unwrap();
        assert!(status.success(), "command failed: {args:?}");
    }

    fn output<const N: usize>(dir: &tempfile::TempDir, args: [&str; N]) -> String {
        let output = Command::new(args[0])
            .args(&args[1..])
            .current_dir(dir.path())
            .output()
            .unwrap();
        assert!(output.status.success(), "command failed: {args:?}");
        String::from_utf8(output.stdout).unwrap()
    }
}
