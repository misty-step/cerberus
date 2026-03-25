defmodule Mix.Tasks.Cerberus.ReviewTest do
  use ExUnit.Case, async: false

  alias Cerberus.TestSupport.LocalReviewRepo
  import ExUnit.CaptureIO

  @repo_root Path.expand("../../..", __DIR__)

  setup do
    Mix.Task.reenable("cerberus.review")
    original = Application.get_env(:cerberus_elixir, :cli_overrides)
    fixture = LocalReviewRepo.create!()

    on_exit(fn ->
      LocalReviewRepo.cleanup!(fixture)

      if original == nil do
        Application.delete_env(:cerberus_elixir, :cli_overrides)
      else
        Application.put_env(:cerberus_elixir, :cli_overrides, original)
      end
    end)

    %{fixture: fixture}
  end

  defp valid_verdict_json do
    Jason.encode!(%{
      "reviewer" => "trace",
      "perspective" => "correctness",
      "verdict" => "PASS",
      "confidence" => 0.85,
      "summary" => "No issues found.",
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

  defp unique_name(prefix) do
    :"#{prefix}_#{System.unique_integer([:positive])}"
  end

  defp cli_overrides do
    [
      repo_root: @repo_root,
      config_name: unique_name("mix_task_cli_config"),
      router_name: unique_name("mix_task_cli_router"),
      review_supervisor_name: unique_name("mix_task_cli_review_supervisor"),
      task_supervisor_name: unique_name("mix_task_cli_task_supervisor"),
      routing_result: %{
        panel: ["trace"],
        reserves: [],
        model_tier: :flash,
        size_bucket: :small,
        routing_used: false
      },
      call_llm: fn _params ->
        {:ok,
         %{
           content: valid_verdict_json(),
           tool_calls: [],
           usage: %{prompt_tokens: 100, completion_tokens: 25}
         }}
      end
    ]
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

  test "run/1 delegates to the shared CLI path", %{fixture: fixture} do
    Application.put_env(:cerberus_elixir, :cli_overrides, cli_overrides())

    output =
      capture_io(fn ->
        Mix.Tasks.Cerberus.Review.run(review_args(fixture) ++ ["--format", "json"])
      end)

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
    assert is_list(decoded["findings"])
    assert is_map(decoded["stats"])
  end

  test "run/1 prints usage for --help without raising" do
    output =
      capture_io(fn ->
        Mix.Tasks.Cerberus.Review.run(["--help"])
      end)

    assert output =~ "Usage:"
    assert output =~ "mix cerberus.review --repo <path> --base <ref> --head <ref>"
    refute output =~ "--diff"
  end
end
