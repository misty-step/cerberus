use crate::{
    probe_harness, provider_budget::provider_budget_acknowledged, read_eval_matrix,
    read_eval_suite, required_arg, scan_stale_models, write_json,
};
use anyhow::{bail, Context, Result};
use cerberus_adapter::CommandHarnessInput;
use cerberus_core::{
    eval_reviewer_config, evaluate_harness_model_artifact, evaluate_harness_model_matrix,
    harness_model_evaluation_output, harness_model_readiness_report,
    unavailable_harness_model_cell, HarnessModelEvaluationOutput, HarnessProbe,
};
use cerberus_schema::{
    EvalCellStatus, EvalExecutionMode, EvalTask, EvalTaskSuite, HarnessModelEvaluationCell,
    HarnessModelMatrix, HarnessProfile, ModelCandidate, PeerHarnessCommandProfile,
    PeerHarnessCommandProfiles, ReviewerArtifact, StaleModelFinding,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    env, fs,
    path::{Path, PathBuf},
    process,
    process::Command,
    time::{Instant, SystemTime, UNIX_EPOCH},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum EvalHarnessMode {
    OfflineContract,
    LivePeer,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct EvalHarnessArgs {
    suite_path: PathBuf,
    matrix_path: PathBuf,
    out_dir: PathBuf,
    execution_mode: EvalHarnessMode,
    peer_profiles_path: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct EvalReadinessArgs {
    suite_path: PathBuf,
    matrix_path: PathBuf,
    peer_profiles_path: PathBuf,
    out_path: PathBuf,
}

impl EvalReadinessArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut suite = None;
        let mut matrix = None;
        let mut peer_profiles = None;
        let mut out = None;
        let mut index = 0;

        while index < args.len() {
            match args[index].as_str() {
                "--suite" => {
                    suite = Some(required_arg(args, index, "--suite")?);
                    index += 2;
                }
                "--matrix" => {
                    matrix = Some(required_arg(args, index, "--matrix")?);
                    index += 2;
                }
                "--peer-profiles" => {
                    peer_profiles = Some(required_arg(args, index, "--peer-profiles")?);
                    index += 2;
                }
                "--out" => {
                    out = Some(required_arg(args, index, "--out")?);
                    index += 2;
                }
                other => bail!("unknown eval-readiness argument {other:?}"),
            }
        }

        Ok(Self {
            suite_path: PathBuf::from(suite.context("eval-readiness requires --suite <path>")?),
            matrix_path: PathBuf::from(matrix.context("eval-readiness requires --matrix <path>")?),
            peer_profiles_path: PathBuf::from(
                peer_profiles.context("eval-readiness requires --peer-profiles <path>")?,
            ),
            out_path: PathBuf::from(out.context("eval-readiness requires --out <path>")?),
        })
    }
}

impl EvalHarnessArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut suite = None;
        let mut matrix = None;
        let mut out = None;
        let mut execution_mode = EvalHarnessMode::OfflineContract;
        let mut peer_profiles = None;
        let mut index = 0;

        while index < args.len() {
            match args[index].as_str() {
                "--suite" => {
                    suite = Some(required_arg(args, index, "--suite")?);
                    index += 2;
                }
                "--matrix" => {
                    matrix = Some(required_arg(args, index, "--matrix")?);
                    index += 2;
                }
                "--out" => {
                    out = Some(required_arg(args, index, "--out")?);
                    index += 2;
                }
                "--execution-mode" => {
                    execution_mode =
                        parse_eval_harness_mode(&required_arg(args, index, "--execution-mode")?)?;
                    index += 2;
                }
                "--peer-profiles" => {
                    peer_profiles =
                        Some(PathBuf::from(required_arg(args, index, "--peer-profiles")?));
                    index += 2;
                }
                other => bail!("unknown eval-harness argument {other:?}"),
            }
        }

        if execution_mode == EvalHarnessMode::LivePeer && peer_profiles.is_none() {
            bail!("eval-harness --execution-mode live-peer requires --peer-profiles <path>");
        }

        Ok(Self {
            suite_path: PathBuf::from(suite.context("eval-harness requires --suite <path>")?),
            matrix_path: PathBuf::from(matrix.context("eval-harness requires --matrix <path>")?),
            out_dir: PathBuf::from(out.context("eval-harness requires --out <dir>")?),
            execution_mode,
            peer_profiles_path: peer_profiles,
        })
    }
}

pub fn eval_harness(args: Vec<String>) -> Result<()> {
    let args = EvalHarnessArgs::parse(&args)?;
    let suite = read_eval_suite(&args.suite_path)?;
    let matrix = read_eval_matrix(&args.matrix_path)?;
    let probes = matrix
        .harnesses
        .iter()
        .map(probe_harness)
        .collect::<Vec<_>>();
    let stale_model_findings = scan_stale_models(&matrix)?;

    fs::create_dir_all(&args.out_dir)
        .with_context(|| format!("failed to create output dir {}", args.out_dir.display()))?;
    let output = match args.execution_mode {
        EvalHarnessMode::OfflineContract => {
            evaluate_harness_model_matrix(&suite, &matrix, &probes, stale_model_findings)?
        }
        EvalHarnessMode::LivePeer => evaluate_live_peer_harness_matrix(
            &suite,
            &matrix,
            &probes,
            stale_model_findings,
            args.peer_profiles_path
                .as_ref()
                .expect("live-peer mode requires peer profiles"),
            &args.out_dir,
        )?,
    };

    let mut transcript_paths = BTreeSet::new();
    for (relative_path, transcript) in &output.transcripts {
        if !transcript_paths.insert(relative_path.as_str()) {
            bail!("duplicate transcript path {relative_path:?}");
        }
        let path = args.out_dir.join(relative_path);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("failed to create transcript dir {}", parent.display()))?;
        }
        fs::write(&path, transcript)
            .with_context(|| format!("failed to write transcript {}", path.display()))?;
    }

    let report_path = args.out_dir.join("report.json");
    write_json(&report_path, &output.report)?;
    println!("{}", report_path.display());
    Ok(())
}

pub fn eval_readiness(args: Vec<String>) -> Result<()> {
    let args = EvalReadinessArgs::parse(&args)?;
    let suite = read_eval_suite(&args.suite_path)?;
    let matrix = read_eval_matrix(&args.matrix_path)?;
    let peer_profiles = read_peer_harness_profiles(&args.peer_profiles_path)?;
    let probes = matrix
        .harnesses
        .iter()
        .map(probe_harness)
        .collect::<Vec<_>>();
    let peer_runner_probes =
        probe_peer_harness_runners(&suite, &matrix, &peer_profiles, &args.peer_profiles_path);
    let available_env = visible_required_env(&peer_profiles);
    let report = harness_model_readiness_report(
        &suite,
        &matrix,
        &probes,
        &peer_runner_probes,
        &peer_profiles,
        &available_env,
        provider_budget_acknowledged(),
    )?;

    write_json(&args.out_path, &report)?;
    println!("{}", args.out_path.display());
    Ok(())
}

fn visible_required_env(peer_profiles: &PeerHarnessCommandProfiles) -> BTreeSet<String> {
    peer_profiles
        .profiles
        .iter()
        .flat_map(|profile| profile.env_required.iter())
        .filter(|name| env::var_os(name.as_str()).is_some())
        .cloned()
        .collect()
}

fn probe_peer_harness_runners(
    suite: &EvalTaskSuite,
    matrix: &HarnessModelMatrix,
    peer_profiles: &PeerHarnessCommandProfiles,
    peer_profiles_path: &Path,
) -> Vec<HarnessProbe> {
    let harness_by_id = matrix
        .harnesses
        .iter()
        .map(|harness| (harness.harness_id.as_str(), harness))
        .collect::<BTreeMap<_, _>>();

    peer_profiles
        .profiles
        .iter()
        .map(|profile| {
            match (
                harness_by_id.get(profile.harness_id.as_str()).copied(),
                matrix.models.first(),
                suite.tasks.first(),
            ) {
                (Some(harness), Some(model), Some(task)) => {
                    probe_peer_harness_runner(profile, peer_profiles_path, harness, model, task)
                }
                _ => HarnessProbe {
                    harness_id: profile.harness_id.clone(),
                    available: false,
                    version: None,
                    path: None,
                    failure_reason: Some(
                        "peer harness runner probe has no representative matrix cell".to_string(),
                    ),
                },
            }
        })
        .collect()
}

fn probe_peer_harness_runner(
    profile: &PeerHarnessCommandProfile,
    peer_profiles_path: &Path,
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
) -> HarnessProbe {
    let command = peer_protocol_command(&profile.command);
    let path = peer_protocol_command_path(&profile.command, &command);
    match run_peer_harness_runner_probe(profile, peer_profiles_path, harness, model, task, &command)
    {
        Ok(()) => HarnessProbe {
            harness_id: profile.harness_id.clone(),
            available: true,
            version: None,
            path,
            failure_reason: None,
        },
        Err(error) => HarnessProbe {
            harness_id: profile.harness_id.clone(),
            available: false,
            version: None,
            path,
            failure_reason: Some(error.to_string()),
        },
    }
}

fn run_peer_harness_runner_probe(
    profile: &PeerHarnessCommandProfile,
    peer_profiles_path: &Path,
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    command: &Path,
) -> Result<()> {
    let temp_dir = env::temp_dir().join(format!(
        "cerberus-readiness-probe-{}-{}-{}",
        sanitize_eval_path_component(&profile.harness_id),
        process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0)
    ));
    fs::create_dir_all(&temp_dir)
        .with_context(|| format!("failed to create probe dir {}", temp_dir.display()))?;

    let input_path = temp_dir.join("input.json");
    let output_path = temp_dir.join("artifact.json");
    let input = CommandHarnessInput {
        reviewer: eval_reviewer_config(harness, model, task),
        request: task.review_request.clone(),
    };
    let probe_result = (|| -> Result<()> {
        write_json(&input_path, &input)?;
        let output = Command::new(command)
            .args(&profile.args)
            .arg("--profiles")
            .arg(peer_profiles_path)
            .arg("--input")
            .arg(&input_path)
            .arg("--output")
            .arg(&output_path)
            .env_remove("CERBERUS_PEER_HARNESS_LIVE")
            .output()
            .with_context(|| format!("{} unavailable", command.display()))?;
        if !output.status.success() {
            bail!(
                "{} probe exited with {}: {}",
                command.display(),
                output.status,
                command_probe_diagnostic(&output)
            );
        }
        read_reviewer_artifact(&output_path).with_context(|| {
            format!("{} probe did not write a valid artifact", command.display())
        })?;
        Ok(())
    })();

    let cleanup_result = fs::remove_dir_all(&temp_dir);
    if probe_result.is_ok() {
        cleanup_result
            .with_context(|| format!("failed to remove probe dir {}", temp_dir.display()))?;
    }
    probe_result
}

fn command_probe_diagnostic(output: &std::process::Output) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let diagnostic = if stderr.trim().is_empty() {
        stdout.trim()
    } else {
        stderr.trim()
    };
    if diagnostic.is_empty() {
        "no diagnostic".to_string()
    } else {
        diagnostic.to_string()
    }
}

fn peer_protocol_command_path(command_name: &str, command: &Path) -> Option<String> {
    if command.components().count() > 1 {
        return command.exists().then(|| command.display().to_string());
    }

    env::var_os("PATH").and_then(|path| {
        env::split_paths(&path)
            .map(|dir| dir.join(command_name))
            .find(|candidate| candidate.exists())
            .map(|candidate| candidate.display().to_string())
    })
}

fn parse_eval_harness_mode(value: &str) -> Result<EvalHarnessMode> {
    match value {
        "offline-contract" | "offline_contract" => Ok(EvalHarnessMode::OfflineContract),
        "live-peer" | "live_peer" => Ok(EvalHarnessMode::LivePeer),
        other => bail!("unknown eval-harness execution mode {other:?}"),
    }
}

fn evaluate_live_peer_harness_matrix(
    suite: &EvalTaskSuite,
    matrix: &HarnessModelMatrix,
    probes: &[HarnessProbe],
    stale_model_findings: Vec<StaleModelFinding>,
    peer_profiles_path: &Path,
    out_dir: &Path,
) -> Result<HarnessModelEvaluationOutput> {
    let peer_profiles = read_peer_harness_profiles(peer_profiles_path)?;
    let peer_profile_by_harness = peer_profiles
        .profiles
        .iter()
        .map(|profile| (profile.harness_id.as_str(), profile))
        .collect::<BTreeMap<_, _>>();
    let probe_by_harness = probes
        .iter()
        .map(|probe| (probe.harness_id.as_str(), probe))
        .collect::<BTreeMap<_, _>>();
    let mut cells = Vec::new();
    let mut transcripts = Vec::new();

    for harness in &matrix.harnesses {
        for model in &matrix.models {
            for task in &suite.tasks {
                let transcript_path = eval_cell_path("transcripts", harness, model, task, "txt");
                let cell = match probe_by_harness.get(harness.harness_id.as_str()) {
                    Some(probe) if !probe.available => unavailable_harness_model_cell(
                        harness,
                        model,
                        task,
                        EvalExecutionMode::LiveHarness,
                        transcript_path.clone(),
                        probe
                            .failure_reason
                            .clone()
                            .unwrap_or_else(|| "harness unavailable".to_string()),
                    ),
                    None => unavailable_harness_model_cell(
                        harness,
                        model,
                        task,
                        EvalExecutionMode::LiveHarness,
                        transcript_path.clone(),
                        "harness was not probed".to_string(),
                    ),
                    Some(_) => match peer_profile_by_harness.get(harness.harness_id.as_str()) {
                        Some(profile) => run_live_peer_eval_cell(
                            harness,
                            model,
                            task,
                            profile,
                            peer_profiles_path,
                            out_dir,
                            &transcript_path,
                        )?,
                        None => unavailable_harness_model_cell(
                            harness,
                            model,
                            task,
                            EvalExecutionMode::LiveHarness,
                            transcript_path.clone(),
                            format!(
                                "peer harness profile {:?} was not found",
                                harness.harness_id
                            ),
                        ),
                    },
                };
                transcripts.push((
                    transcript_path.clone(),
                    read_eval_transcript(out_dir, &transcript_path, &cell)?,
                ));
                cells.push(cell);
            }
        }
    }

    Ok(harness_model_evaluation_output(
        suite,
        matrix,
        cells,
        transcripts,
        stale_model_findings,
    )?)
}

fn run_live_peer_eval_cell(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    profile: &PeerHarnessCommandProfile,
    peer_profiles_path: &Path,
    out_dir: &Path,
    transcript_relative_path: &str,
) -> Result<HarnessModelEvaluationCell> {
    let input_relative_path = eval_cell_path("inputs", harness, model, task, "json");
    let artifact_relative_path = eval_cell_path("artifacts", harness, model, task, "json");
    let plan_relative_path = eval_cell_path("plans", harness, model, task, "json");
    let input_path = out_dir.join(&input_relative_path);
    let artifact_path = out_dir.join(&artifact_relative_path);
    let transcript_path = out_dir.join(transcript_relative_path);
    let plan_path = out_dir.join(&plan_relative_path);

    let input = CommandHarnessInput {
        reviewer: eval_reviewer_config(harness, model, task),
        request: task.review_request.clone(),
    };
    write_json(&input_path, &input)?;
    ensure_parent_dir(&artifact_path)?;
    ensure_parent_dir(&transcript_path)?;
    ensure_parent_dir(&plan_path)?;
    remove_stale_eval_file(&artifact_path)?;
    remove_stale_eval_file(&transcript_path)?;
    remove_stale_eval_file(&plan_path)?;

    let started = Instant::now();
    let output = Command::new(peer_protocol_command(&profile.command))
        .args(&profile.args)
        .arg("--profiles")
        .arg(peer_profiles_path)
        .arg("--input")
        .arg(&input_path)
        .arg("--output")
        .arg(&artifact_path)
        .arg("--transcript-output")
        .arg(&transcript_path)
        .arg("--execution-plan-output")
        .arg(&plan_path)
        .env("CERBERUS_PEER_HARNESS_LIVE", "1")
        .output()
        .with_context(|| {
            format!(
                "failed to launch live peer harness command for {}",
                harness.harness_id
            )
        })?;
    let latency_ms = started.elapsed().as_millis().try_into().unwrap_or(u64::MAX);

    if !output.status.success() {
        let reason = command_failure_reason(&profile.command, &output);
        write_eval_transcript(
            &transcript_path,
            &format!(
                "live peer eval command failed\nstatus: {}\nstdout:\n{}\nstderr:\n{}\n",
                output.status,
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            ),
        )?;
        return Ok(unavailable_harness_model_cell(
            harness,
            model,
            task,
            EvalExecutionMode::LiveHarness,
            transcript_relative_path.to_string(),
            reason,
        ));
    }

    let artifact = read_reviewer_artifact(&artifact_path)?;
    Ok(evaluate_harness_model_artifact(
        harness,
        model,
        task,
        EvalExecutionMode::LiveHarness,
        artifact,
        latency_ms,
        transcript_relative_path.to_string(),
    )?)
}

fn read_peer_harness_profiles(path: &Path) -> Result<PeerHarnessCommandProfiles> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read peer harness profiles {}", path.display()))?;
    let profiles: PeerHarnessCommandProfiles = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse peer harness profiles {}", path.display()))?;
    profiles.validate()?;
    Ok(profiles)
}

fn read_reviewer_artifact(path: &Path) -> Result<ReviewerArtifact> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read reviewer artifact {}", path.display()))?;
    let artifact: ReviewerArtifact = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse reviewer artifact {}", path.display()))?;
    Ok(artifact)
}

fn peer_protocol_command(command: &str) -> PathBuf {
    if command == "cerberus-peer-harness" {
        if let Ok(current_exe) = env::current_exe() {
            let sibling = current_exe.with_file_name("cerberus-peer-harness");
            if sibling.exists() {
                return sibling;
            }
        }
    }
    PathBuf::from(command)
}

fn command_failure_reason(command: &str, output: &std::process::Output) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let diagnostic = if stderr.trim().is_empty() {
        stdout.trim()
    } else {
        stderr.trim()
    };
    if diagnostic.is_empty() {
        format!("{command:?} exited with {}", output.status)
    } else {
        format!("{command:?} exited with {}: {diagnostic}", output.status)
    }
}

fn read_eval_transcript(
    out_dir: &Path,
    relative_path: &str,
    cell: &HarnessModelEvaluationCell,
) -> Result<String> {
    let path = out_dir.join(relative_path);
    match fs::read_to_string(&path) {
        Ok(transcript) => Ok(transcript),
        Err(_) if cell.status == EvalCellStatus::Unavailable => Ok(format!(
            "cell_id: {}\nharness: {}\nmodel: {}\ntask: {}\nstatus: {:?}\nfailure_reason: {}\n",
            cell.cell_id,
            cell.harness_id,
            cell.model_id,
            cell.task_id,
            cell.status,
            cell.failure_reason.as_deref().unwrap_or("none")
        )),
        Err(error) => {
            Err(error).with_context(|| format!("failed to read eval transcript {}", path.display()))
        }
    }
}

fn write_eval_transcript(path: &Path, transcript: &str) -> Result<()> {
    ensure_parent_dir(path)?;
    fs::write(path, transcript)
        .with_context(|| format!("failed to write transcript {}", path.display()))
}

fn ensure_parent_dir(path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create output dir {}", parent.display()))?;
    }
    Ok(())
}

fn remove_stale_eval_file(path: &Path) -> Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error)
            .with_context(|| format!("failed to remove stale eval file {}", path.display())),
    }
}

fn eval_cell_path(
    directory: &str,
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    extension: &str,
) -> String {
    format!(
        "{directory}/{}.{}",
        sanitize_eval_path_component(&format!(
            "{}__{}__{}",
            harness.harness_id, model.model_id, task.task_id
        )),
        extension
    )
}

fn sanitize_eval_path_component(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '-' || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect()
}
