use std::{fs, path::PathBuf};

#[test]
fn action_entrypoint_invokes_rust_dispatcher() {
    let action = action_yml();

    assert!(
        !action.contains("dispatch.sh"),
        "action.yml should not invoke dispatch.sh after Rust entrypoint wiring"
    );
    assert_contains(&action, "id: dispatch");
    assert_contains(&action, "shell: bash");
    assert_contains(
        &action,
        "CARGO_TARGET_DIR=\"${RUNNER_TEMP:-/tmp}/cerberus-cargo-target\"",
    );
    assert!(
        !action.contains("cargo run"),
        "action.yml should build with scrubbed secrets before runtime execution"
    );
    assert_contains(&action, "unset CERBERUS_API_KEY GITHUB_TOKEN");
    assert_contains(&action, "cargo build --locked");
    assert_contains(&action, "GITHUB_ACTION_PATH: ${{ github.action_path }}");
    assert_contains(
        &action,
        "--manifest-path \"$GITHUB_ACTION_PATH/Cargo.toml\"",
    );
    assert_contains(&action, "-p cerberus-cli");
    assert_contains(&action, "--bin cerberus-cli");
    assert_contains(
        &action,
        "\"$CARGO_TARGET_DIR/debug/cerberus-cli\" github-action-dispatch",
    );
}

#[test]
fn legacy_shell_dispatcher_is_archived() {
    let root = workspace_root();

    assert!(
        !root.join("dispatch.sh").exists(),
        "dispatch.sh should stay archived after the Rust action entrypoint has parity"
    );
}

#[test]
fn action_entrypoint_preserves_consumer_env_and_outputs() {
    let action = action_yml();

    for expected in [
        "value: ${{ steps.dispatch.outputs.verdict }}",
        "value: ${{ steps.dispatch.outputs.review-id }}",
        "CERBERUS_API_KEY: ${{ inputs.api-key }}",
        "CERBERUS_URL: ${{ inputs.cerberus-url }}",
        "CERBERUS_MODEL: ${{ inputs.model }}",
        "CERBERUS_TIMEOUT: ${{ inputs.timeout }}",
        "CERBERUS_POLL_INTERVAL: ${{ inputs.poll-interval }}",
        "CERBERUS_FAIL_ON_VERDICT: ${{ inputs.fail-on-verdict }}",
        "GITHUB_TOKEN: ${{ inputs.github-token }}",
        "PR_NUMBER: ${{ github.event.pull_request.number }}",
        "HEAD_SHA: ${{ github.event.pull_request.head.sha }}",
        "BASE_REPO: ${{ github.event.pull_request.base.repo.full_name }}",
        "HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}",
        "IS_DRAFT: ${{ github.event.pull_request.draft }}",
    ] {
        assert_contains(&action, expected);
    }
}

fn action_yml() -> String {
    fs::read_to_string(workspace_root().join("action.yml")).expect("action.yml")
}

fn workspace_root() -> PathBuf {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .expect("workspace root")
        .to_path_buf();
    root
}

fn assert_contains(haystack: &str, needle: &str) {
    assert!(
        haystack.contains(needle),
        "action.yml missing expected fragment:\n{needle}"
    );
}
