use crate::{
    probe_harness, provider_budget::provider_budget_acknowledged, read_eval_matrix,
    read_eval_suite, required_arg, scan_stale_models, write_json,
};
use anyhow::{bail, Context, Result};
use cerberus_adapter::CommandHarnessInput;
use cerberus_core::{
    eval_budget_estimate_report, eval_reviewer_config, evaluate_harness_model_artifact,
    evaluate_harness_model_matrix, harness_model_evaluation_output, harness_model_readiness_report,
    unavailable_harness_model_cell, HarnessModelEvaluationOutput, HarnessProbe,
};
use cerberus_schema::{
    EvalCellStatus, EvalExecutionMode, EvalReadinessCell, EvalReadinessReport,
    EvalReadinessSummary, EvalTask, EvalTaskSuite, HarnessModelEvaluationCell, HarnessModelMatrix,
    HarnessProfile, ModelCandidate, PeerHarnessCommandProfile, PeerHarnessCommandProfiles,
    ReviewerArtifact, StaleModelFinding,
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
    selection: EvalSelection,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct EvalReadinessArgs {
    suite_path: PathBuf,
    matrix_path: PathBuf,
    peer_profiles_path: PathBuf,
    out_path: PathBuf,
    selection: EvalSelection,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct EvalBudgetArgs {
    suite_path: PathBuf,
    matrix_path: PathBuf,
    readiness_path: PathBuf,
    prompt_tokens: u64,
    completion_tokens: u64,
    retry_count: u64,
    out_path: PathBuf,
    selection: EvalSelection,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
struct EvalSelection {
    harness_ids: BTreeSet<String>,
    model_ids: BTreeSet<String>,
    task_ids: BTreeSet<String>,
}

impl EvalSelection {
    fn add_harness(&mut self, value: String) -> Result<()> {
        insert_selector(&mut self.harness_ids, value, "--harness")
    }

    fn add_model(&mut self, value: String) -> Result<()> {
        insert_selector(&mut self.model_ids, value, "--model")
    }

    fn add_task(&mut self, value: String) -> Result<()> {
        insert_selector(&mut self.task_ids, value, "--task")
    }

    fn is_empty(&self) -> bool {
        self.harness_ids.is_empty() && self.model_ids.is_empty() && self.task_ids.is_empty()
    }
}

impl EvalBudgetArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut suite = None;
        let mut matrix = None;
        let mut readiness = None;
        let mut prompt_tokens = None;
        let mut completion_tokens = None;
        let mut retry_count = 1;
        let mut out = None;
        let mut selection = EvalSelection::default();
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
                "--readiness" => {
                    readiness = Some(required_arg(args, index, "--readiness")?);
                    index += 2;
                }
                "--prompt-tokens" => {
                    prompt_tokens = Some(parse_positive_u64(
                        &required_arg(args, index, "--prompt-tokens")?,
                        "--prompt-tokens",
                    )?);
                    index += 2;
                }
                "--completion-tokens" => {
                    completion_tokens = Some(parse_positive_u64(
                        &required_arg(args, index, "--completion-tokens")?,
                        "--completion-tokens",
                    )?);
                    index += 2;
                }
                "--retry-count" => {
                    retry_count = parse_positive_u64(
                        &required_arg(args, index, "--retry-count")?,
                        "--retry-count",
                    )?;
                    index += 2;
                }
                "--out" => {
                    out = Some(required_arg(args, index, "--out")?);
                    index += 2;
                }
                "--harness" => {
                    selection.add_harness(required_arg(args, index, "--harness")?)?;
                    index += 2;
                }
                "--model" => {
                    selection.add_model(required_arg(args, index, "--model")?)?;
                    index += 2;
                }
                "--task" => {
                    selection.add_task(required_arg(args, index, "--task")?)?;
                    index += 2;
                }
                other => bail!("unknown eval-budget argument {other:?}"),
            }
        }

        Ok(Self {
            suite_path: PathBuf::from(suite.context("eval-budget requires --suite <path>")?),
            matrix_path: PathBuf::from(matrix.context("eval-budget requires --matrix <path>")?),
            readiness_path: PathBuf::from(
                readiness.context("eval-budget requires --readiness <path>")?,
            ),
            prompt_tokens: prompt_tokens
                .context("eval-budget requires --prompt-tokens <positive-int>")?,
            completion_tokens: completion_tokens
                .context("eval-budget requires --completion-tokens <positive-int>")?,
            retry_count,
            out_path: PathBuf::from(out.context("eval-budget requires --out <path>")?),
            selection,
        })
    }
}

impl EvalReadinessArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut suite = None;
        let mut matrix = None;
        let mut peer_profiles = None;
        let mut out = None;
        let mut selection = EvalSelection::default();
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
                "--harness" => {
                    selection.add_harness(required_arg(args, index, "--harness")?)?;
                    index += 2;
                }
                "--model" => {
                    selection.add_model(required_arg(args, index, "--model")?)?;
                    index += 2;
                }
                "--task" => {
                    selection.add_task(required_arg(args, index, "--task")?)?;
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
            selection,
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
        let mut selection = EvalSelection::default();
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
                "--harness" => {
                    selection.add_harness(required_arg(args, index, "--harness")?)?;
                    index += 2;
                }
                "--model" => {
                    selection.add_model(required_arg(args, index, "--model")?)?;
                    index += 2;
                }
                "--task" => {
                    selection.add_task(required_arg(args, index, "--task")?)?;
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
            selection,
        })
    }
}

pub fn eval_harness(args: Vec<String>) -> Result<()> {
    let args = EvalHarnessArgs::parse(&args)?;
    let suite = read_eval_suite(&args.suite_path)?;
    let matrix = read_eval_matrix(&args.matrix_path)?;
    let (suite, matrix) = select_eval_inputs(suite, matrix, &args.selection)?;
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
    let (suite, matrix) = select_eval_inputs(suite, matrix, &args.selection)?;
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

pub fn eval_budget(args: Vec<String>) -> Result<()> {
    let args = EvalBudgetArgs::parse(&args)?;
    let suite = read_eval_suite(&args.suite_path)?;
    let matrix = read_eval_matrix(&args.matrix_path)?;
    let (suite, matrix) = select_eval_inputs(suite, matrix, &args.selection)?;
    let readiness = read_eval_readiness_report(&args.readiness_path)?;
    let readiness = select_eval_readiness(readiness, &suite, &matrix, &args.selection)?;
    let report = eval_budget_estimate_report(
        &suite,
        &matrix,
        &readiness,
        args.prompt_tokens,
        args.completion_tokens,
        args.retry_count,
    )?;

    write_json(&args.out_path, &report)?;
    println!("{}", args.out_path.display());
    Ok(())
}

fn insert_selector(selectors: &mut BTreeSet<String>, value: String, flag: &str) -> Result<()> {
    if value.trim().is_empty() {
        bail!("{flag} requires a non-empty value");
    }
    if !selectors.insert(value.clone()) {
        bail!("duplicate eval selector for {flag}: {value:?}");
    }
    Ok(())
}

fn select_eval_inputs(
    mut suite: EvalTaskSuite,
    mut matrix: HarnessModelMatrix,
    selection: &EvalSelection,
) -> Result<(EvalTaskSuite, HarnessModelMatrix)> {
    if selection.is_empty() {
        return Ok((suite, matrix));
    }

    validate_selected_ids(
        "harness",
        &selection.harness_ids,
        matrix
            .harnesses
            .iter()
            .map(|harness| harness.harness_id.as_str()),
    )?;
    validate_selected_ids(
        "model",
        &selection.model_ids,
        matrix.models.iter().map(|model| model.model_id.as_str()),
    )?;
    validate_selected_ids(
        "task",
        &selection.task_ids,
        suite.tasks.iter().map(|task| task.task_id.as_str()),
    )?;

    if !selection.harness_ids.is_empty() {
        matrix
            .harnesses
            .retain(|harness| selection.harness_ids.contains(&harness.harness_id));
    }
    if !selection.model_ids.is_empty() {
        matrix
            .models
            .retain(|model| selection.model_ids.contains(&model.model_id));
    }
    if !selection.task_ids.is_empty() {
        suite
            .tasks
            .retain(|task| selection.task_ids.contains(&task.task_id));
    }

    suite.validate()?;
    matrix.validate()?;
    Ok((suite, matrix))
}

fn validate_selected_ids<'a>(
    label: &str,
    requested: &BTreeSet<String>,
    known: impl Iterator<Item = &'a str>,
) -> Result<()> {
    if requested.is_empty() {
        return Ok(());
    }
    let known = known.collect::<BTreeSet<_>>();
    let unknown = requested
        .iter()
        .filter(|id| !known.contains(id.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    if !unknown.is_empty() {
        bail!("unknown eval {label} selector(s): {}", unknown.join(", "));
    }
    Ok(())
}

fn select_eval_readiness(
    mut readiness: EvalReadinessReport,
    suite: &EvalTaskSuite,
    matrix: &HarnessModelMatrix,
    selection: &EvalSelection,
) -> Result<EvalReadinessReport> {
    if selection.is_empty() {
        return Ok(readiness);
    }

    let expected = selected_cell_keys(suite, matrix);
    readiness.cells.retain(|cell| {
        expected.contains(&(
            cell.harness_id.clone(),
            cell.model_id.clone(),
            cell.task_id.clone(),
        ))
    });
    let observed = readiness
        .cells
        .iter()
        .map(|cell| {
            (
                cell.harness_id.clone(),
                cell.model_id.clone(),
                cell.task_id.clone(),
            )
        })
        .collect::<BTreeSet<_>>();
    if observed != expected {
        let missing = expected
            .difference(&observed)
            .next()
            .map(|(harness_id, model_id, task_id)| format!("{harness_id}/{model_id}/{task_id}"))
            .unwrap_or_else(|| "unknown".to_string());
        bail!("readiness report does not cover selected eval cell {missing:?}");
    }
    readiness.summary = readiness_summary(&readiness.cells);
    readiness.validate()?;
    Ok(readiness)
}

fn selected_cell_keys(
    suite: &EvalTaskSuite,
    matrix: &HarnessModelMatrix,
) -> BTreeSet<(String, String, String)> {
    let mut keys = BTreeSet::new();
    for harness in &matrix.harnesses {
        for model in &matrix.models {
            for task in &suite.tasks {
                keys.insert((
                    harness.harness_id.clone(),
                    model.model_id.clone(),
                    task.task_id.clone(),
                ));
            }
        }
    }
    keys
}

fn readiness_summary(cells: &[EvalReadinessCell]) -> EvalReadinessSummary {
    EvalReadinessSummary {
        total_cells: cells.len() as u64,
        runnable_cells: cells.iter().filter(|cell| cell.runnable).count() as u64,
        unavailable_harness_cells: cells.iter().filter(|cell| !cell.harness_available).count()
            as u64,
        unavailable_peer_runner_cells: cells
            .iter()
            .filter(|cell| cell.peer_profile_found && !cell.peer_runner_available)
            .count() as u64,
        missing_profile_cells: cells.iter().filter(|cell| !cell.peer_profile_found).count() as u64,
        missing_env_cells: cells
            .iter()
            .filter(|cell| !cell.env_missing.is_empty())
            .count() as u64,
        budget_blocked_cells: cells
            .iter()
            .filter(|cell| cell.requires_provider_budget_ack && !cell.provider_budget_acknowledged)
            .count() as u64,
    }
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

fn parse_positive_u64(value: &str, flag: &'static str) -> Result<u64> {
    let parsed = value
        .parse::<u64>()
        .with_context(|| format!("{flag} must be a positive integer"))?;
    if parsed == 0 {
        bail!("{flag} must be greater than zero");
    }
    Ok(parsed)
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

fn read_eval_readiness_report(path: &Path) -> Result<EvalReadinessReport> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read eval readiness report {}", path.display()))?;
    let report: EvalReadinessReport = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse eval readiness report {}", path.display()))?;
    report.validate()?;
    Ok(report)
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

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_core::harness_model_readiness_report;
    use cerberus_schema::{EvalBudgetEstimateReport, HarnessModelEvaluationReport};

    fn repo_path(relative: &str) -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("crates dir")
            .parent()
            .expect("repo root")
            .join(relative)
    }

    fn temp_dir(label: &str) -> PathBuf {
        let dir = env::temp_dir().join(format!(
            "cerberus-eval-subset-{label}-{}-{}",
            process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|duration| duration.as_nanos())
                .unwrap_or(0)
        ));
        fs::create_dir_all(&dir).expect("temp dir");
        dir
    }

    fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> T {
        let raw = fs::read_to_string(path).expect("read json");
        serde_json::from_str(&raw).expect("parse json")
    }

    fn matrix_with_absolute_drift_paths(temp: &Path) -> PathBuf {
        let source = repo_path("fixtures/evals/harness-model-matrix.json");
        let mut matrix = read_eval_matrix(&source).expect("matrix");
        matrix.drift_scan_paths = matrix
            .drift_scan_paths
            .iter()
            .map(|path| repo_path(path).display().to_string())
            .collect();
        let path = temp.join("matrix.absolute-drift.json");
        write_json(&path, &matrix).expect("write matrix");
        path
    }

    #[test]
    fn eval_harness_filters_to_selected_cells() {
        let out = temp_dir("harness");
        let matrix_path = matrix_with_absolute_drift_paths(&out);

        eval_harness(vec![
            "--suite".to_string(),
            repo_path("fixtures/evals/reviewer-harness-smoke.json")
                .display()
                .to_string(),
            "--matrix".to_string(),
            matrix_path.display().to_string(),
            "--harness".to_string(),
            "goose".to_string(),
            "--model".to_string(),
            "z-ai/glm-5.2".to_string(),
            "--task".to_string(),
            "clean-no-finding".to_string(),
            "--out".to_string(),
            out.display().to_string(),
        ])
        .expect("selected eval succeeds");

        let report: HarnessModelEvaluationReport = read_json(&out.join("report.json"));
        report.validate().expect("report validates");
        assert_eq!(report.summary.total_cells, 1);
        let cell = &report.cells[0];
        assert_eq!(cell.harness_id, "goose");
        assert_eq!(cell.model_id, "z-ai/glm-5.2");
        assert_eq!(cell.task_id, "clean-no-finding");
        assert!(out.join(&cell.transcript_path).exists());
    }

    #[test]
    fn eval_budget_filters_full_readiness_report_to_selected_cells() {
        let temp = temp_dir("budget");
        let suite_path = repo_path("fixtures/evals/reviewer-harness-smoke.json");
        let matrix_path = repo_path("fixtures/evals/harness-model-matrix.json");
        let profile_path = repo_path("fixtures/harnesses/peer-command-profiles.json");
        let suite = read_eval_suite(&suite_path).expect("suite");
        let matrix = read_eval_matrix(&matrix_path).expect("matrix");
        let peer_profiles = read_peer_harness_profiles(&profile_path).expect("profiles");
        let probes = matrix
            .harnesses
            .iter()
            .map(|harness| HarnessProbe {
                harness_id: harness.harness_id.clone(),
                available: true,
                version: harness.version.clone(),
                path: harness.path.clone(),
                failure_reason: None,
            })
            .collect::<Vec<_>>();
        let peer_runner_probes = matrix
            .harnesses
            .iter()
            .map(|harness| HarnessProbe {
                harness_id: harness.harness_id.clone(),
                available: true,
                version: None,
                path: Some("/bin/cerberus-peer-harness".to_string()),
                failure_reason: None,
            })
            .collect::<Vec<_>>();
        let readiness = harness_model_readiness_report(
            &suite,
            &matrix,
            &probes,
            &peer_runner_probes,
            &peer_profiles,
            &BTreeSet::from(["OPENROUTER_API_KEY".to_string()]),
            false,
        )
        .expect("readiness");
        let readiness_path = temp.join("readiness.json");
        write_json(&readiness_path, &readiness).expect("write readiness");
        let out = temp.join("budget.json");

        eval_budget(vec![
            "--suite".to_string(),
            suite_path.display().to_string(),
            "--matrix".to_string(),
            matrix_path.display().to_string(),
            "--readiness".to_string(),
            readiness_path.display().to_string(),
            "--harness".to_string(),
            "goose".to_string(),
            "--model".to_string(),
            "z-ai/glm-5.2".to_string(),
            "--task".to_string(),
            "clean-no-finding".to_string(),
            "--prompt-tokens".to_string(),
            "20000".to_string(),
            "--completion-tokens".to_string(),
            "4000".to_string(),
            "--out".to_string(),
            out.display().to_string(),
        ])
        .expect("selected budget succeeds");

        let report: EvalBudgetEstimateReport = read_json(&out);
        report.validate().expect("budget report validates");
        assert_eq!(report.summary.total_cells, 1);
        assert_eq!(report.summary.estimateable_cells, 1);
        let cell = &report.cells[0];
        assert_eq!(cell.harness_id, "goose");
        assert_eq!(cell.model_id, "z-ai/glm-5.2");
        assert_eq!(cell.task_id, "clean-no-finding");
    }

    #[test]
    fn eval_readiness_rejects_unknown_selector() {
        let out = temp_dir("readiness").join("readiness.json");

        let error = eval_readiness(vec![
            "--suite".to_string(),
            repo_path("fixtures/evals/reviewer-harness-smoke.json")
                .display()
                .to_string(),
            "--matrix".to_string(),
            repo_path("fixtures/evals/harness-model-matrix.json")
                .display()
                .to_string(),
            "--peer-profiles".to_string(),
            repo_path("fixtures/harnesses/peer-command-profiles.json")
                .display()
                .to_string(),
            "--harness".to_string(),
            "missing-harness".to_string(),
            "--out".to_string(),
            out.display().to_string(),
        ])
        .expect_err("unknown selector is rejected");

        assert!(error.to_string().contains("unknown eval harness selector"));
        assert!(!out.exists());
    }
}
