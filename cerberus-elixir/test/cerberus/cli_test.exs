defmodule Cerberus.CLITest do
  use ExUnit.Case, async: false

  alias Cerberus.CLI
  alias Cerberus.TestSupport.LocalReviewRepo
  import ExUnit.CaptureIO

  @repo_root Path.expand("../../..", __DIR__)

  defp verdict_json(verdict, summary \\ nil) do
    Jason.encode!(%{
      "reviewer" => "trace",
      "perspective" => "correctness",
      "verdict" => verdict,
      "confidence" => 0.85,
      "summary" => summary || "#{verdict} summary.",
      "findings" => [],
      "stats" => %{
        "files_reviewed" => 1,
        "files_with_issues" => 0,
        "critical" => 0,
        "major" => 0,
        "minor" => 0,
        "info" => 0
      }
    })
  end

  defp valid_verdict_json, do: verdict_json("PASS")

  defp unique_name(prefix) do
    :"#{prefix}_#{System.unique_integer([:positive])}"
  end

  defp routing_result(panel \\ ["trace"]) do
    %{
      panel: panel,
      reserves: [],
      model_tier: :flash,
      size_bucket: :small,
      routing_used: false
    }
  end

  setup do
    fixture = LocalReviewRepo.create!()
    on_exit(fn -> LocalReviewRepo.cleanup!(fixture) end)
    %{fixture: fixture}
  end

  defp cli_opts(extra \\ []) do
    [
      repo_root: @repo_root,
      config_name: unique_name("cli_config"),
      router_name: unique_name("cli_router"),
      review_supervisor_name: unique_name("cli_review_supervisor"),
      task_supervisor_name: unique_name("cli_task_supervisor"),
      routing_result: routing_result(),
      call_llm: fn _params ->
        {:ok,
         %{
           content: valid_verdict_json(),
           tool_calls: [],
           usage: %{prompt_tokens: 100, completion_tokens: 25}
         }}
      end
    ]
    |> Keyword.merge(extra)
  end

  defp review_args(fixture, base_ref \\ nil, head_ref \\ nil) do
    [
      "--repo",
      fixture.root,
      "--base",
      base_ref || fixture.base_sha,
      "--head",
      head_ref || fixture.head_sha
    ]
  end

  defp decode_run!(argv, opts) do
    assert {:ok, output} = CLI.run(argv ++ ["--format", "json"], opts)
    Jason.decode!(output)
  end

  defp sequence_mock(responses) do
    {:ok, agent} = Agent.start_link(fn -> responses end)

    mock = fn params ->
      Agent.get_and_update(agent, fn
        [{:fun, fun} | rest] -> {fun.(params), rest}
        [resp | rest] -> {resp, rest}
        [] -> {{:error, :exhausted}, []}
      end)
    end

    {mock, agent}
  end

  test "run/2 emits machine-parseable JSON for a ref range", %{fixture: fixture} do
    assert {:ok, output} =
             CLI.run(
               review_args(fixture) ++ ["--format", "json"],
               cli_opts()
             )

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
    assert is_list(decoded["findings"])
    assert is_map(decoded["stats"])
  end

  test "run/2 tolerates the release subcommand prefix", %{fixture: fixture} do
    assert {:ok, output} =
             CLI.run(
               ["review", "--"] ++ review_args(fixture) ++ ["--format", "json"],
               cli_opts()
             )

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
  end

  test "run/2 defaults to human-readable text output", %{fixture: fixture} do
    assert {:ok, output} =
             CLI.run(
               review_args(fixture),
               cli_opts()
             )

    assert output =~ "Verdict: PASS"
    assert output =~ "Summary: All reviewers passed."
    assert output =~ "Findings:"
  end

  test "run/2 emits an explicit no-changes result without planner or reviewer work", %{
    fixture: fixture
  } do
    test_pid = self()

    assert {:ok, output} =
             CLI.run(
               review_args(fixture, fixture.head_sha, fixture.head_sha),
               cli_opts(
                 call_llm: fn _params ->
                   send(test_pid, :reviewer_called)
                   {:error, :unexpected}
                 end,
                 router_call_llm: fn _params ->
                   send(test_pid, :router_called)
                   {:error, :unexpected}
                 end
               )
             )

    assert output =~ "No changes to review"
    refute_receive :reviewer_called
    refute_receive :router_called
  end

  test "run/2 resolves representative commit-ish refs from outside the target repo without mutation",
       %{fixture: fixture} do
    refs = [
      {fixture.revision_base_ref, fixture.branch_ref},
      {fixture.base_sha, fixture.tag_ref},
      {fixture.base_sha, fixture.head_sha},
      {fixture.base_sha, fixture.short_head_sha}
    ]

    before_head = LocalReviewRepo.head(fixture.root)
    before_status = LocalReviewRepo.status(fixture.root)
    before_worktrees = LocalReviewRepo.worktree_list(fixture.root)

    File.cd!(System.tmp_dir!(), fn ->
      Enum.each(refs, fn {base_ref, head_ref} ->
        decoded = decode_run!(review_args(fixture, base_ref, head_ref), cli_opts())
        assert decoded["verdict"] == "PASS"
      end)
    end)

    assert LocalReviewRepo.head(fixture.root) == before_head
    assert LocalReviewRepo.status(fixture.root) == before_status
    assert LocalReviewRepo.worktree_list(fixture.root) == before_worktrees
  end

  test "run/2 uses a materialized workspace instead of the caller checkout", %{fixture: fixture} do
    tool_call = %{
      id: "call_1",
      function: %{name: "get_file_contents", arguments: ~s({"path": "lib/sample.ex"})}
    }

    test_pid = self()

    {mock, _agent} =
      sequence_mock([
        {:ok,
         %{
           content: nil,
           tool_calls: [tool_call],
           usage: %{prompt_tokens: 100, completion_tokens: 20}
         }},
        {:fun,
         fn params ->
           send(test_pid, {:tool_messages, params.messages})

           {:ok,
            %{
              content: valid_verdict_json(),
              tool_calls: [],
              usage: %{prompt_tokens: 200, completion_tokens: 100}
            }}
         end}
      ])

    decoded =
      decode_run!(
        review_args(fixture),
        cli_opts(call_llm: mock)
      )

    assert decoded["verdict"] == "PASS"

    assert_receive {:tool_messages, messages}

    tool_message =
      Enum.find(messages, fn message ->
        message["role"] == "tool" and message["tool_call_id"] == "call_1"
      end)

    assert tool_message["content"] == fixture.head_content
    assert tool_message["content"] != fixture.dirty_content
  end

  test "run/2 surfaces runtime startup failures", %{fixture: fixture} do
    assert {:error, {message, 1}} =
             CLI.run(
               review_args(fixture),
               cli_opts(review_supervisor_name: self())
             )

    assert message =~ "Failed to start CLI runtime"
  end

  test "run/2 degrades reviewer failures to a skip verdict", %{fixture: fixture} do
    decoded =
      decode_run!(
        review_args(fixture),
        cli_opts(call_llm: fn _params -> {:error, :boom} end)
      )

    assert decoded["verdict"] == "SKIP"
    assert decoded["summary"] =~ "1 skipped"
    assert decoded["stats"]["skip"] == 1
  end

  test "run/2 degrades reviewer crashes to a skip verdict", %{fixture: fixture} do
    decoded =
      decode_run!(
        review_args(fixture),
        cli_opts(call_llm: fn _params -> Process.exit(self(), :kill) end)
      )

    assert decoded["verdict"] == "SKIP"
    assert decoded["stats"]["skip"] == 1
  end

  test "run/2 degrades reviewer timeouts to a skip verdict", %{fixture: fixture} do
    reviewer_timeout = 50
    sleep_ms = reviewer_timeout + 5_000 + 1_000

    decoded =
      decode_run!(
        review_args(fixture),
        cli_opts(
          reviewer_timeout: reviewer_timeout,
          call_llm: fn _params ->
            Process.sleep(sleep_ms)

            {:ok,
             %{
               content: valid_verdict_json(),
               tool_calls: [],
               usage: %{prompt_tokens: 100, completion_tokens: 25}
             }}
          end
        )
      )

    assert decoded["verdict"] == "SKIP"
    assert decoded["stats"]["skip"] == 1
  end

  test "execute/2 returns deterministic exit codes for completed review verdicts", %{
    fixture: fixture
  } do
    assert {:ok, %{verdict: "PASS", exit_code: 0}} =
             CLI.execute(review_args(fixture), cli_opts())

    assert {:ok, %{verdict: "WARN", exit_code: 0}} =
             CLI.execute(
               review_args(fixture),
               cli_opts(
                 call_llm: fn _params ->
                   {:ok,
                    %{
                      content: verdict_json("WARN", "Potential issue found."),
                      tool_calls: [],
                      usage: %{prompt_tokens: 100, completion_tokens: 25}
                    }}
                 end
               )
             )

    assert {:ok, %{verdict: "SKIP", exit_code: 0}} =
             CLI.execute(
               review_args(fixture, fixture.head_sha, fixture.head_sha),
               cli_opts()
             )

    assert {:ok, %{verdict: "FAIL", exit_code: 2}} =
             CLI.execute(
               review_args(fixture),
               cli_opts(
                 routing_result: routing_result(["trace", "guard"]),
                 call_llm: fn _params ->
                   {:ok,
                    %{
                      content: verdict_json("FAIL", "Blocking issue found."),
                      tool_calls: [],
                      usage: %{prompt_tokens: 100, completion_tokens: 25}
                    }}
                 end
               )
             )
  end

  test "execute/2 uses a distinct non-zero exit code for invocation/runtime failures", %{
    fixture: fixture
  } do
    assert {:ok, %{exit_code: fail_code, verdict: "FAIL"}} =
             CLI.execute(
               review_args(fixture),
               cli_opts(
                 routing_result: routing_result(["trace", "guard"]),
                 call_llm: fn _params ->
                   {:ok,
                    %{
                      content: verdict_json("FAIL", "Blocking issue found."),
                      tool_calls: [],
                      usage: %{prompt_tokens: 100, completion_tokens: 25}
                    }}
                 end
               )
             )

    assert {:error, %{exit_code: invocation_code, message: invocation_message}} =
             CLI.execute(["--unknown"], cli_opts())

    assert invocation_code == 1
    assert invocation_message =~ "Unsupported options"

    assert {:error, %{exit_code: runtime_code, message: runtime_message}} =
             CLI.execute(
               review_args(fixture),
               cli_opts(review_supervisor_name: self())
             )

    assert runtime_code == 1
    assert runtime_message =~ "Failed to start CLI runtime"
    assert fail_code != invocation_code
    assert fail_code != runtime_code
  end

  test "run/2 surfaces routing failures when the router crashes", %{fixture: fixture} do
    assert {:error, {message, 1}} =
             CLI.run(
               review_args(fixture),
               cli_opts(
                 routing_result: nil,
                 router_call_llm: fn _params -> Process.exit(self(), :kill) end
               )
             )

    assert message =~ "Routing failed"
  end

  test "main/2 prints successful output without halting when halt is false", %{fixture: fixture} do
    output =
      capture_io(fn ->
        assert :ok =
                 CLI.main(
                   review_args(fixture) ++ ["--format", "json"],
                   cli_opts(halt: false)
                 )
      end)

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
  end

  test "main/2 prints actionable errors to stderr without halting when halt is false" do
    message =
      capture_io(:stderr, fn ->
        assert {:error, returned_message} =
                 CLI.main(
                   ["--repo", "/definitely/missing/repo", "--base", "main", "--head", "HEAD"],
                   cli_opts(halt: false)
                 )

        assert returned_message =~ "Repository path not found for --repo"
      end)

    assert message =~ "Repository path not found for --repo"
  end

  test "run/2 validates CLI argument errors", %{fixture: fixture} do
    assert {:error, {message, 1}} = CLI.run(["--unknown"], cli_opts())
    assert message =~ "Unsupported options"

    assert {:error, {message, 1}} = CLI.run(review_args(fixture) ++ ["extra"], cli_opts())
    assert message =~ "Unexpected arguments"

    assert {:error, {message, 1}} = CLI.run([], cli_opts())
    assert message =~ "Missing required options: --repo, --base, --head"

    assert {:error, {message, 1}} =
             CLI.run(review_args(fixture) ++ ["--format", "yaml"], cli_opts())

    assert message =~ "Unsupported format: yaml"

    assert {:error, {message, 1}} =
             CLI.run(["--diff", "range.diff"], cli_opts())

    assert message =~ "Legacy --diff input is no longer supported"
  end

  test "run/2 rejects invalid repo inputs before review work", %{fixture: fixture} do
    non_git_dir =
      Path.join(System.tmp_dir!(), "cerberus_non_git_#{System.unique_integer([:positive])}")

    File.mkdir_p!(non_git_dir)
    on_exit(fn -> File.rm_rf(non_git_dir) end)

    assert {:error, {message, 1}} =
             CLI.run(
               ["--repo", "/definitely/missing/repo", "--base", "main", "--head", "HEAD"],
               cli_opts()
             )

    assert message =~ "Repository path not found for --repo"

    assert {:error, {message, 1}} =
             CLI.run(
               ["--repo", non_git_dir, "--base", fixture.base_sha, "--head", fixture.head_sha],
               cli_opts()
             )

    assert message =~ "--repo is not inside a Git repository"
  end

  test "run/2 rejects invalid refs before workspace or review work", %{fixture: fixture} do
    test_pid = self()

    assert {:error, {message, 1}} =
             CLI.run(
               ["--repo", fixture.root, "--base", fixture.base_sha, "--head", "missing-ref"],
               cli_opts(
                 call_llm: fn _params ->
                   send(test_pid, :reviewer_called)
                   {:error, :unexpected}
                 end,
                 router_call_llm: fn _params ->
                   send(test_pid, :router_called)
                   {:error, :unexpected}
                 end
               )
             )

    assert message =~ ~s(Could not resolve --head ref "missing-ref")
    refute_receive :reviewer_called
    refute_receive :router_called
  end

  test "run/2 rejects invalid config overrides before planner or reviewer work", %{
    fixture: fixture
  } do
    test_pid = self()

    assert {:error, {message, 1}} =
             CLI.run(
               review_args(fixture),
               cli_opts(
                 config_overrides: %{
                   unsupported: true,
                   routing: %{panel_size: "oops"}
                 },
                 call_llm: fn _params ->
                   send(test_pid, :reviewer_called)
                   {:error, :unexpected}
                 end,
                 router_call_llm: fn _params ->
                   send(test_pid, :router_called)
                   {:error, :unexpected}
                 end
               )
             )

    assert message =~ "Invalid Cerberus reviewer configuration"
    assert message =~ "overrides.unsupported"
    assert message =~ "routing.panel_size"
    refute_receive :reviewer_called
    refute_receive :router_called
  end

  test "run/2 rejects unsupported override strings before planner or reviewer work", %{
    fixture: fixture
  } do
    test_pid = self()
    invalid_perspective = "unknown_perspective_#{System.unique_integer([:positive])}"
    invalid_override = "unknown_override_#{System.unique_integer([:positive])}"
    invalid_tier = "unknown_wave_#{System.unique_integer([:positive])}"

    assert {:error, {message, 1}} =
             CLI.run(
               review_args(fixture),
               cli_opts(
                 config_overrides: %{
                   reviewers: %{
                     trace: %{
                       perspective: invalid_perspective,
                       override: invalid_override
                     }
                   },
                   model_pools: %{
                     invalid_tier => ["kimi_k2_5"]
                   }
                 },
                 call_llm: fn _params ->
                   send(test_pid, :reviewer_called)
                   {:error, :unexpected}
                 end,
                 router_call_llm: fn _params ->
                   send(test_pid, :router_called)
                   {:error, :unexpected}
                 end
               )
             )

    assert message =~ "Invalid Cerberus reviewer configuration"
    assert message =~ "reviewers.trace.perspective"
    assert message =~ "unsupported perspective"
    assert message =~ "reviewers.trace.override"
    assert message =~ "unsupported override policy"
    assert message =~ "model_pools.#{invalid_tier}"
    assert message =~ "unsupported model pool tier"
    refute_receive :reviewer_called
    refute_receive :router_called
  end
end
