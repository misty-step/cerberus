//! Container-isolated review substrate (backlog 013 M2).
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
//! Docker container. Network egress is narrowed to exactly one host —
//! [`ContainerOpencodeSubstrateConfig::egress_allow_host`], normally the
//! model API — via a small topology: the review container joins a
//! `--internal` Docker network (no route to the WAN at all) whose only
//! reachable peer is a `squid` forward-proxy container that itself also
//! joins the default (real-egress) network, configured to allow `CONNECT`
//! to exactly the allowed host and deny everything else. `squid` never
//! terminates TLS — it only reads the `CONNECT` target from the plaintext
//! request line and then splices raw bytes — so it never sees whatever
//! credential flows through the tunnel it opens.
//!
//! A prompt-injected agent trying to reach a second host has no route to it
//! at the network layer, not just a denied HTTP request: even DNS
//! resolution for a name other than the allowed one has nowhere to go, since
//! the container has no path to any DNS server either.
//!
//! Crash safety mirrors [`crate::openrouter_keys`]: an RAII guard
//! ([`EgressProxyGuard`]) tears down the proxy container and network when
//! this function returns (success, error, or panic) within-process, and
//! [`sweep_orphaned_container_resources`] — run at the start of every call,
//! before creating anything new — cleans up whatever a `SIGKILL`ed prior run
//! left behind, the same way [`crate::openrouter_keys::sweep_orphaned_keys`]
//! does for credentials. `--rm` alone is not enough: it only removes a
//! container on its own exit, which dockerd manages independently of
//! whether the `cerberus` process that started it is still alive.

use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

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

/// Default single host:port the egress proxy allows `CONNECT` to. Every
/// model call in this codebase goes through OpenRouter.
pub const DEFAULT_EGRESS_ALLOW_HOST: &str = "openrouter.ai:443";

/// Where the disposable host root (archived workspace + request/prompt files)
/// is mounted inside the container. Fixed and unconfigurable: every path the
/// agent is told about is relative to this, so there is exactly one place to
/// audit for host-path leakage.
const CONTAINER_MOUNT_ROOT: &str = "/cerberus";
const CONTAINER_BINARY_PATH: &str = "/usr/local/bin/cerberus-substrate";

/// Shared prefix for every review AND proxy container this module creates.
/// Both `sweep_orphaned_container_resources` and `docker ps --filter` key
/// off this — the timestamp always immediately follows it (see
/// `timestamped_name`), so age-parsing is uniform across both container
/// kinds.
const CONTAINER_NAME_PREFIX: &str = "cerberus-review-";
/// Separate prefix/namespace for the per-run internal network (networks and
/// containers are different Docker object types, swept independently).
const NETWORK_NAME_PREFIX: &str = "cerberus-review-net-";

/// A well-audited, purpose-built forward proxy, not custom Rust: allowlisted
/// `CONNECT`-tunnel forwarding is exactly squid's job, and reimplementing
/// TLS-tunnel relaying by hand is precisely the kind of security-sensitive
/// protocol surface backlog 013's round-1 critique warned about. Pulled as a
/// stock image — no build step, no maintenance burden beyond a config file.
const PROXY_IMAGE: &str = "ubuntu/squid:latest";
const PROXY_PORT: u16 = 3128;

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
    /// The single `host:port` the egress proxy allows `CONNECT` to. See
    /// [`DEFAULT_EGRESS_ALLOW_HOST`].
    pub egress_allow_host: String,
    /// Age past which the orphan sweeper removes a stale review or proxy
    /// container (and per-run network) left by a crashed prior run, before
    /// creating this run's own resources.
    pub orphan_sweep_max_age: Duration,
}

pub(crate) fn run_container_substrate(
    request: &ReviewRequest,
    timeout: Duration,
    config: &ContainerOpencodeSubstrateConfig,
) -> Result<HarnessRun> {
    let swept =
        sweep_orphaned_container_resources(&config.docker_binary, config.orphan_sweep_max_age);
    if !swept.is_empty() {
        eprintln!(
            "cerberus: orphan sweep removed {} stale container-opencode resource(s) from a prior run",
            swept.len()
        );
    }

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

    // Guard is bound to a local so it stays alive (Rust never drops a Drop
    // type early, regardless of NLL) until this function returns by any
    // path — success, `?`, or panic — tearing the proxy + network down
    // exactly then. A SIGKILL of this process is the one path Drop cannot
    // cover; sweep_orphaned_container_resources above is what closes that
    // window, on the next call.
    let egress_proxy =
        start_egress_proxy(&config.docker_binary, &config.egress_allow_host, host_root)?;
    let env_file = write_allowed_env_file(request, host_root)?;

    let container_name = timestamped_name(CONTAINER_NAME_PREFIX);
    let docker_args = docker_run_args(
        &container_name,
        host_root,
        config,
        &egress_proxy.network,
        &egress_proxy.proxy_url(),
        env_file.as_deref(),
        &container_args,
    );

    let plan = ExecutionPlan {
        harness: "container-opencode".to_string(),
        command: config.docker_binary.clone(),
        args: docker_args.clone(),
        cwd: host_root.display().to_string(),
        timeout_ms: timeout.as_millis() as u64,
        env_allowlist: request.policy.allowed_env.clone(),
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
        "[container-opencode]\nname: {container_name}\negress_allow_host: {}\nexit_status: {}\nelapsed_ms: {}\n\n[stdout]\n{}\n\n[stderr]\n{}\n",
        config.egress_allow_host,
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
    network: &str,
    proxy_url: &str,
    env_file: Option<&Path>,
    container_args: &[String],
) -> Vec<String> {
    let mut args: Vec<String> = vec![
        "run".to_string(),
        "--rm".to_string(),
        "--name".to_string(),
        container_name.to_string(),
        // Run as the host's own uid:gid, not root. --cap-drop ALL removes
        // CAP_DAC_OVERRIDE, so a root-owned process without it can no longer
        // rely on root's usual permission bypass — it would need the mounted
        // host_root's owning uid to match anyway. Matching uid:gid up front
        // is both the permission fix and the hardening: the sandboxed agent
        // never runs as container-root at all.
        "--user".to_string(),
        current_uid_gid(),
        // The review container's ONLY network peer is the egress proxy
        // (same --internal network); the proxy itself enforces the
        // single-host allowlist. Belt-and-suspenders HTTP_PROXY/HTTPS_PROXY
        // in both cases, since different tools respect different casing.
        "--network".to_string(),
        network.to_string(),
        "-e".to_string(),
        format!("HTTPS_PROXY={proxy_url}"),
        "-e".to_string(),
        format!("https_proxy={proxy_url}"),
        "-e".to_string(),
        format!("HTTP_PROXY={proxy_url}"),
        "-e".to_string(),
        format!("http_proxy={proxy_url}"),
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
    ];
    if let Some(env_file) = env_file {
        args.push("--env-file".to_string());
        args.push(env_file.display().to_string());
    }
    args.push("--entrypoint".to_string());
    args.push(CONTAINER_BINARY_PATH.to_string());
    args.push(config.image.clone());
    args.extend(container_args.iter().cloned());
    args
}

#[cfg(unix)]
fn current_uid_gid() -> String {
    // SAFETY: getuid/getgid take no arguments and cannot fail.
    let (uid, gid) = unsafe { (libc::getuid(), libc::getgid()) };
    format!("{uid}:{gid}")
}

#[cfg(not(unix))]
fn current_uid_gid() -> String {
    "1000:1000".to_string()
}

/// `<prefix><unix-seconds>-<8-hex-id>` — the timestamp always comes
/// immediately after the prefix, for both review containers
/// (`CONTAINER_NAME_PREFIX`) and proxy containers (also
/// `CONTAINER_NAME_PREFIX`, since a proxy name is
/// `cerberus-review-<ts>-<id>-proxy`), so `resource_age` parses either
/// uniformly. The id is deliberately short: the review container resolves
/// the proxy container by *name* over the internal Docker network's
/// embedded DNS, and DNS labels cap at 63 octets (RFC 1035) — a full UUID
/// pushed `cerberus-review-<ts>-<uuid>-proxy` past that limit, which failed
/// silently (the name just didn't resolve) rather than erroring at
/// creation. 8 hex chars plus the second-resolution timestamp is
/// astronomically collision-safe for this run rate.
fn timestamped_name(prefix: &str) -> String {
    let unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or(Duration::ZERO)
        .as_secs();
    let short_id = Uuid::new_v4().simple().to_string();
    format!("{prefix}{unix_seconds}-{}", &short_id[..8])
}

fn resource_age(name: &str, prefix: &str, now: SystemTime) -> Option<Duration> {
    let suffix = name.strip_prefix(prefix)?;
    let unix_seconds: u64 = suffix.split('-').next()?.parse().ok()?;
    let created_at = UNIX_EPOCH + Duration::from_secs(unix_seconds);
    now.duration_since(created_at).ok()
}

/// Crash-safety net for the network/container objects a `SIGKILL`ed prior
/// run left behind — `--rm` only removes a container on its own exit, which
/// dockerd manages independent of whether `cerberus` itself is still alive.
/// Run at the start of every `run_container_substrate` call, before this
/// run's own resources exist, exactly like
/// [`crate::openrouter_keys::sweep_orphaned_keys`]. Every failure is
/// logged and skipped, never propagated — an orphan sweep must never block
/// an otherwise-healthy review.
fn sweep_orphaned_container_resources(docker_binary: &str, max_age: Duration) -> Vec<String> {
    let now = SystemTime::now();
    let mut swept = Vec::new();

    let container_names = list_docker_resource_names(
        docker_binary,
        &["ps", "-a"],
        CONTAINER_NAME_PREFIX,
        "{{.Names}}",
        "orphan container sweep",
    );
    for name in container_names {
        let Some(age) = resource_age(&name, CONTAINER_NAME_PREFIX, now) else {
            continue;
        };
        if age < max_age {
            continue;
        }
        match Command::new(docker_binary)
            .args(["rm", "-f", &name])
            .output()
        {
            Ok(output) if output.status.success() => swept.push(name),
            Ok(output) => eprintln!(
                "cerberus: orphan sweep failed to remove stale container {name}: {}",
                String::from_utf8_lossy(&output.stderr)
            ),
            Err(err) => {
                eprintln!("cerberus: orphan sweep failed to remove stale container {name}: {err:#}")
            }
        }
    }

    // Networks after containers: a network can't be removed while any
    // container (even a stopped one) is still attached to it.
    let network_names = list_docker_resource_names(
        docker_binary,
        &["network", "ls"],
        NETWORK_NAME_PREFIX,
        "{{.Name}}",
        "orphan network sweep",
    );
    for name in network_names {
        let Some(age) = resource_age(&name, NETWORK_NAME_PREFIX, now) else {
            continue;
        };
        if age < max_age {
            continue;
        }
        match Command::new(docker_binary)
            .args(["network", "rm", &name])
            .output()
        {
            Ok(output) if output.status.success() => swept.push(name),
            Ok(output) => eprintln!(
                "cerberus: orphan sweep failed to remove stale network {name}: {}",
                String::from_utf8_lossy(&output.stderr)
            ),
            Err(err) => {
                eprintln!("cerberus: orphan sweep failed to remove stale network {name}: {err:#}")
            }
        }
    }

    swept
}

fn list_docker_resource_names(
    docker_binary: &str,
    subcommand: &[&str],
    name_prefix: &str,
    name_format: &str,
    label: &str,
) -> Vec<String> {
    let output = Command::new(docker_binary)
        .args(subcommand)
        .args([
            "--filter",
            &format!("name={name_prefix}"),
            "--format",
            name_format,
        ])
        .output();
    match output {
        Ok(output) if output.status.success() => String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(str::to_string)
            .filter(|line| !line.is_empty())
            .collect(),
        Ok(output) => {
            eprintln!(
                "cerberus: {label} listing failed (continuing): {}",
                String::from_utf8_lossy(&output.stderr)
            );
            Vec::new()
        }
        Err(err) => {
            eprintln!("cerberus: {label} listing failed (continuing): {err:#}");
            Vec::new()
        }
    }
}

/// Holds the per-run egress proxy container and its `--internal` network,
/// and tears both down on `Drop` — the same crash-safety shape as
/// [`crate::openrouter_keys::ScopedKeyGuard`]: covers a panic or an early
/// `?` return within this process; a `SIGKILL` is what
/// `sweep_orphaned_container_resources` exists to clean up on the next run.
struct EgressProxyGuard<'a> {
    docker_binary: &'a str,
    proxy_container: String,
    network: String,
}

impl EgressProxyGuard<'_> {
    fn proxy_url(&self) -> String {
        format!("http://{}:{PROXY_PORT}", self.proxy_container)
    }
}

impl Drop for EgressProxyGuard<'_> {
    fn drop(&mut self) {
        let rm = Command::new(self.docker_binary)
            .args(["rm", "-f", &self.proxy_container])
            .output();
        if let Err(err) = &rm {
            eprintln!(
                "cerberus: failed to remove egress proxy container {}: {err:#}",
                self.proxy_container
            );
        }
        match Command::new(self.docker_binary)
            .args(["network", "rm", &self.network])
            .output()
        {
            Ok(output) if output.status.success() => {}
            Ok(output) => eprintln!(
                "cerberus: failed to remove egress proxy network {}: {}",
                self.network,
                String::from_utf8_lossy(&output.stderr)
            ),
            Err(err) => eprintln!(
                "cerberus: failed to remove egress proxy network {}: {err:#}",
                self.network
            ),
        }
    }
}

fn parse_host_port(spec: &str) -> Result<(String, u16)> {
    if spec.chars().any(char::is_whitespace) {
        return Err(anyhow!(
            "egress allow-host {spec:?} must not contain whitespace"
        ));
    }
    let (host, port) = spec
        .rsplit_once(':')
        .ok_or_else(|| anyhow!("egress allow-host {spec:?} must be host:port"))?;
    let port: u16 = port
        .parse()
        .with_context(|| format!("egress allow-host {spec:?} has an invalid port"))?;
    if host.is_empty() {
        return Err(anyhow!("egress allow-host {spec:?} has an empty host"));
    }
    Ok((host.to_string(), port))
}

/// Allows `CONNECT` to exactly one host:port and nothing else. `squid` reads
/// the target straight off the `CONNECT` request line, so this works
/// without ever decrypting the TLS tunnel it relays.
fn squid_config(allow_domain: &str, allow_port: u16) -> String {
    format!(
        "http_port {PROXY_PORT}\n\
         acl allowed_connect_host dstdomain {allow_domain}\n\
         acl allowed_connect_port port {allow_port}\n\
         acl CONNECT method CONNECT\n\
         http_access allow CONNECT allowed_connect_host allowed_connect_port\n\
         http_access deny CONNECT\n\
         http_access deny all\n"
    )
}

fn start_egress_proxy<'a>(
    docker_binary: &'a str,
    allow_host_port: &str,
    host_root: &Path,
) -> Result<EgressProxyGuard<'a>> {
    let (allow_domain, allow_port) = parse_host_port(allow_host_port)?;
    let squid_conf_path = host_root.join("squid.conf");
    fs::write(&squid_conf_path, squid_config(&allow_domain, allow_port))
        .context("write egress proxy config")?;
    set_private_permissions(&squid_conf_path)?;

    let review_ts_uuid = timestamped_name(CONTAINER_NAME_PREFIX);
    let ts_uuid_suffix = review_ts_uuid
        .strip_prefix(CONTAINER_NAME_PREFIX)
        .expect("timestamped_name always carries its own prefix");
    let network_name = format!("{NETWORK_NAME_PREFIX}{ts_uuid_suffix}");
    let proxy_name = format!("{CONTAINER_NAME_PREFIX}{ts_uuid_suffix}-proxy");

    let create_network = Command::new(docker_binary)
        .args(["network", "create", "--internal", &network_name])
        .output()
        .context("create egress-isolated Docker network")?;
    if !create_network.status.success() {
        return Err(anyhow!(
            "create egress-isolated Docker network {network_name} failed: {}",
            String::from_utf8_lossy(&create_network.stderr)
        ));
    }

    // The proxy starts on the default (real-egress) network first, so it
    // can actually reach the allowed host; connecting it to the internal
    // network second gives the review container a peer to route through
    // without ever giving the review container itself a route to the WAN.
    let run_proxy = Command::new(docker_binary)
        .args(["run", "-d", "--name", &proxy_name, "-v"])
        .arg(format!(
            "{}:/etc/squid/squid.conf:ro",
            squid_conf_path.display()
        ))
        .arg(PROXY_IMAGE)
        .output()
        .context("start egress proxy container")?;
    if !run_proxy.status.success() {
        let _ = Command::new(docker_binary)
            .args(["network", "rm", &network_name])
            .output();
        return Err(anyhow!(
            "start egress proxy container {proxy_name} failed: {}",
            String::from_utf8_lossy(&run_proxy.stderr)
        ));
    }

    let connect_network = Command::new(docker_binary)
        .args(["network", "connect", &network_name, &proxy_name])
        .output();
    let connect_ok = matches!(&connect_network, Ok(output) if output.status.success());
    if !connect_ok {
        let _ = Command::new(docker_binary)
            .args(["rm", "-f", &proxy_name])
            .output();
        let _ = Command::new(docker_binary)
            .args(["network", "rm", &network_name])
            .output();
        let detail = match connect_network {
            Ok(output) => String::from_utf8_lossy(&output.stderr).into_owned(),
            Err(err) => err.to_string(),
        };
        return Err(anyhow!(
            "connect egress proxy {proxy_name} to {network_name} failed: {detail}"
        ));
    }

    let guard = EgressProxyGuard {
        docker_binary,
        proxy_container: proxy_name.clone(),
        network: network_name,
    };

    wait_for_proxy_ready(docker_binary, &proxy_name)?;

    Ok(guard)
}

/// `pgrep squid` only proves the process was exec'd, not that it has
/// finished `listen()`ing on `PROXY_PORT` yet — on a loaded CI runner the
/// gap between the two was wide enough for the review container's first
/// `CONNECT` to lose the race and fail outright. squid logs the exact line
/// below the moment it starts accepting connections, so check that instead
/// of inferring readiness from process existence.
fn wait_for_proxy_ready(docker_binary: &str, proxy_name: &str) -> Result<()> {
    for _ in 0..50 {
        if let Ok(output) = Command::new(docker_binary)
            .args(["logs", proxy_name])
            .output()
        {
            let combined = [output.stdout.as_slice(), output.stderr.as_slice()].concat();
            if String::from_utf8_lossy(&combined).contains("Accepting HTTP Socket connections") {
                return Ok(());
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Err(anyhow!(
        "egress proxy {proxy_name} did not become ready within 10s"
    ))
}

/// Forwards `request.policy.allowed_env` into the review container via
/// `--env-file` rather than `-e NAME=VALUE`: `-e` values are visible in
/// `docker inspect`/`ps` on the host, and a scoped OpenRouter key (backlog
/// 013 M1) is exactly the kind of value that flows through here. A file
/// under the already-0700 `host_root`, further locked to 0600, keeps it out
/// of argv without adding a new secret-handling primitive.
fn write_allowed_env_file(request: &ReviewRequest, host_root: &Path) -> Result<Option<PathBuf>> {
    let mut contents = String::new();
    for key in &request.policy.allowed_env {
        if let Ok(value) = std::env::var(key) {
            contents.push_str(key);
            contents.push('=');
            contents.push_str(&value);
            contents.push('\n');
        }
    }
    if contents.is_empty() {
        return Ok(None);
    }
    let path = host_root.join("container.env");
    fs::write(&path, contents).context("write container env file")?;
    set_private_permissions(&path)?;
    Ok(Some(path))
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

    #[test]
    fn timestamped_name_round_trips_through_resource_age() {
        let minted_at = UNIX_EPOCH + Duration::from_secs(2_000_000);
        // timestamped_name always stamps SystemTime::now(); reconstruct the
        // parse side directly against a known instant instead of sleeping.
        let name = format!("{CONTAINER_NAME_PREFIX}2000000-abc123");
        let now = minted_at + Duration::from_secs(45);

        let age = resource_age(&name, CONTAINER_NAME_PREFIX, now).expect("age parses back out");

        assert_eq!(age, Duration::from_secs(45));
    }

    #[test]
    fn resource_age_parses_proxy_names_uniformly_with_review_names() {
        // A proxy name is `<prefix><ts>-proxy-<uuid>` -- the timestamp must
        // still be the first segment after the shared prefix so one sweep
        // pass ages both container kinds the same way.
        let now = UNIX_EPOCH + Duration::from_secs(1_000_100);
        let proxy_name = format!("{CONTAINER_NAME_PREFIX}1000000-proxy-abc123");

        let age = resource_age(&proxy_name, CONTAINER_NAME_PREFIX, now).expect("age parses");

        assert_eq!(age, Duration::from_secs(100));
    }

    #[test]
    fn resource_age_ignores_names_without_the_prefix() {
        assert!(resource_age(
            "some-other-container",
            CONTAINER_NAME_PREFIX,
            SystemTime::now()
        )
        .is_none());
    }

    #[test]
    fn timestamped_name_is_freshly_parseable() {
        let name = timestamped_name(CONTAINER_NAME_PREFIX);
        let age = resource_age(&name, CONTAINER_NAME_PREFIX, SystemTime::now())
            .expect("a name minted just now must parse");
        assert!(
            age < Duration::from_secs(5),
            "age should be near zero: {age:?}"
        );
    }

    #[test]
    fn parse_host_port_splits_domain_and_port() {
        let (domain, port) = parse_host_port("openrouter.ai:443").unwrap();
        assert_eq!(domain, "openrouter.ai");
        assert_eq!(port, 443);
    }

    #[test]
    fn parse_host_port_rejects_missing_port() {
        assert!(parse_host_port("openrouter.ai").is_err());
    }

    #[test]
    fn parse_host_port_rejects_whitespace() {
        assert!(parse_host_port("open router.ai:443").is_err());
        assert!(parse_host_port("openrouter.ai:443\ndeny_all off").is_err());
    }

    #[test]
    fn squid_config_allows_only_the_given_host_and_port() {
        let config = squid_config("openrouter.ai", 443);
        assert!(config.contains("dstdomain openrouter.ai"));
        assert!(config.contains("port 443"));
        assert!(config.contains("http_access deny CONNECT"));
        assert!(config.contains("http_access deny all"));
    }

    #[test]
    fn env_file_is_none_when_nothing_is_forwarded() {
        let temp = tempfile::tempdir().unwrap();
        let request = diff_only_request();

        let env_file = write_allowed_env_file(&request, temp.path()).unwrap();

        assert!(env_file.is_none());
    }

    #[test]
    fn env_file_forwards_only_present_allowed_vars() {
        let temp = tempfile::tempdir().unwrap();
        let mut request = diff_only_request();
        request.policy.allowed_env = vec![
            "CERBERUS_CONTAINER_ENV_TEST_PRESENT".to_string(),
            "CERBERUS_CONTAINER_ENV_TEST_ABSENT".to_string(),
        ];
        std::env::set_var("CERBERUS_CONTAINER_ENV_TEST_PRESENT", "sk-or-v1-example");

        let env_file = write_allowed_env_file(&request, temp.path()).unwrap();

        std::env::remove_var("CERBERUS_CONTAINER_ENV_TEST_PRESENT");
        let path = env_file.expect("at least one allowed var was present");
        let contents = fs::read_to_string(path).unwrap();
        assert_eq!(
            contents,
            "CERBERUS_CONTAINER_ENV_TEST_PRESENT=sk-or-v1-example\n"
        );
    }
}
