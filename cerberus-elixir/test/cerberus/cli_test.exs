defmodule Cerberus.CLITest do
  use ExUnit.Case, async: false

  alias Cerberus.CLI
  import ExUnit.CaptureIO

  @repo_root Path.expand("../../..", __DIR__)
  @diff """
  diff --git a/lib/foo.ex b/lib/foo.ex
  --- a/lib/foo.ex
  +++ b/lib/foo.ex
  @@ -1,3 +1,4 @@
   defmodule Foo do
  +  def bar, do: :ok
   end
  """

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

  defp cli_opts(extra \\ []) do
    [
      repo_root: @repo_root,
      config_name: unique_name("cli_config"),
      router_name: unique_name("cli_router"),
      review_supervisor_name: unique_name("cli_review_supervisor"),
      task_supervisor_name: unique_name("cli_task_supervisor"),
      routing_result: %{
        panel: ["correctness"],
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
    |> Keyword.merge(extra)
  end

  defp write_diff!(content \\ @diff) do
    path =
      Path.join(System.tmp_dir!(), "cerberus_cli_diff_#{System.unique_integer([:positive])}.diff")

    File.write!(path, content)
    path
  end

  test "run/2 emits machine-parseable JSON for a diff file" do
    diff_path = write_diff!()

    assert {:ok, output} =
             CLI.run(
               ["--diff", diff_path, "--format", "json"],
               cli_opts()
             )

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
    assert is_list(decoded["findings"])
    assert is_map(decoded["stats"])
  end

  test "run/2 tolerates the release subcommand prefix" do
    diff_path = write_diff!()

    assert {:ok, output} =
             CLI.run(
               ["review", "--", "--diff", diff_path, "--format", "json"],
               cli_opts()
             )

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
  end

  test "run/2 reads diff text from stdin when --diff -" do
    assert {:ok, output} =
             CLI.run(
               ["--diff", "-", "--format", "json"],
               cli_opts(stdin: @diff)
             )

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
    assert Map.has_key?(decoded, "stats")
  end

  test "run/2 defaults to human-readable text output" do
    diff_path = write_diff!()

    assert {:ok, output} =
             CLI.run(
               ["--diff", diff_path],
               cli_opts()
             )

    assert output =~ "Verdict: PASS"
    assert output =~ "Summary: All reviewers passed."
    assert output =~ "Findings:"
  end

  test "run/2 rejects empty diff files" do
    diff_path = write_diff!("")

    assert {:error, {message, 1}} =
             CLI.run(
               ["--diff", diff_path],
               cli_opts()
             )

    assert message =~ "Diff file is empty"
  end

  test "run/2 surfaces runtime startup failures" do
    diff_path = write_diff!()

    assert {:error, {message, 1}} =
             CLI.run(
               ["--diff", diff_path],
               cli_opts(review_supervisor_name: self())
             )

    assert message =~ "Failed to start CLI runtime"
  end

  test "main/2 prints successful output without halting when halt is false" do
    diff_path = write_diff!()

    output =
      capture_io(fn ->
        assert :ok =
                 CLI.main(
                   ["--diff", diff_path, "--format", "json"],
                   cli_opts(halt: false)
                 )
      end)

    decoded = Jason.decode!(output)
    assert decoded["verdict"] == "PASS"
  end

  test "main/2 prints errors to stderr without halting when halt is false" do
    missing_path =
      Path.join(System.tmp_dir!(), "cerberus_cli_missing_#{System.unique_integer([:positive])}.diff")

    message =
      capture_io(:stderr, fn ->
        assert {:error, returned_message} =
                 CLI.main(
                   ["--diff", missing_path],
                   cli_opts(halt: false)
                 )

        assert returned_message =~ "Failed to read diff file"
      end)

    assert message =~ "Failed to read diff file"
    assert message =~ missing_path
  end

  test "run/2 validates CLI argument errors" do
    diff_path = write_diff!()

    assert {:error, {message, 1}} = CLI.run(["--unknown"], cli_opts())
    assert message =~ "Unsupported options"

    assert {:error, {message, 1}} = CLI.run(["--diff", diff_path, "extra"], cli_opts())
    assert message =~ "Unexpected arguments"

    assert {:error, {message, 1}} = CLI.run([], cli_opts())
    assert message =~ "Missing required --diff option"

    assert {:error, {message, 1}} =
             CLI.run(["--diff", diff_path, "--format", "yaml"], cli_opts())

    assert message =~ "Unsupported format: yaml"
  end
end
