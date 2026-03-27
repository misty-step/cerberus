defmodule Cerberus.CLI do
  @moduledoc """
  Local ref-range review entrypoint shared by the mix task and packaged CLI.
  """

  alias Cerberus.{Review, ReviewWorkspace}
  alias Cerberus.Tools.LocalRepoReadHandler

  @switches [repo: :string, base: :string, head: :string, format: :string, help: :boolean]
  @aliases [r: :repo, b: :base, f: :format, h: :help]
  @default_timeout_ms 600_000
  @success_exit_code 0
  @runtime_failure_exit_code 1
  @blocking_verdict_exit_code 2

  @type completed_result :: %{
          output: String.t(),
          exit_code: non_neg_integer(),
          verdict: String.t() | nil
        }
  @type failed_result :: %{message: String.t(), exit_code: pos_integer()}

  @spec usage() :: String.t()
  def usage do
    """
    Usage:
      mix cerberus.review --repo <path> --base <ref> --head <ref> [--format json|text]
      cerberus review --repo <path> --base <ref> --head <ref> [--format json|text]
    """
    |> String.trim_trailing()
  end

  @spec execute([String.t()], keyword()) :: {:ok, completed_result()} | {:error, failed_result()}
  def execute(argv, opts \\ []) do
    opts = Keyword.merge(Application.get_env(:cerberus_elixir, :cli_overrides, []), opts)
    argv = normalize_argv(argv)

    case parse_args(argv) do
      {:ok, request} ->
        execute_request(request, opts)

      {:error, {message, 0}} ->
        {:ok, %{output: message, exit_code: @success_exit_code, verdict: nil}}

      {:error, {message, code}} ->
        {:error, %{message: message, exit_code: code}}
    end
  end

  @spec run([String.t()], keyword()) :: {:ok, String.t()} | {:error, {String.t(), pos_integer()}}
  def run(argv, opts \\ []) do
    case execute(argv, opts) do
      {:ok, %{output: output}} ->
        {:ok, output}

      {:error, %{message: message, exit_code: code}} ->
        {:error, {message, code}}
    end
  end

  defp execute_request(request, opts) do
    with {:ok, workspace} <- prepare_workspace(request) do
      try do
        result =
          if workspace.no_changes? do
            no_changes_result(workspace)
          else
            with {:ok, aggregated} <-
                   with_runtime(opts, &review_workspace(&1, request, workspace, opts)) do
              aggregated
            end
          end

        case result do
          {:error, {message, code}} ->
            {:error, %{message: message, exit_code: code}}

          aggregated ->
            {:ok, completed_result(aggregated, request, workspace, request.format)}
        end
      after
        ReviewWorkspace.cleanup(workspace)
      end
    else
      {:error, {message, code}} ->
        {:error, %{message: message, exit_code: code}}
    end
  end

  @spec main([String.t()], keyword()) :: :ok | {:error, String.t()}
  def main(argv \\ System.argv(), opts \\ []) do
    case execute(argv, opts) do
      {:ok, %{output: output, exit_code: exit_code}} ->
        print_stdout(output)
        maybe_halt(exit_code, opts)
        :ok

      {:error, %{message: message, exit_code: exit_code}} ->
        IO.puts(:stderr, message)
        maybe_halt(exit_code, opts)
        {:error, message}
    end
  end

  defp parse_args(argv) do
    if legacy_diff_option?(argv) do
      {:error, {legacy_diff_message(), 1}}
    else
      {opts, rest, invalid} = OptionParser.parse(argv, strict: @switches, aliases: @aliases)
      missing = missing_required_opts(opts)

      cond do
        opts[:help] ->
          {:error, {usage(), 0}}

        invalid != [] ->
          {:error, {"Unsupported options: #{format_invalid(invalid)}\n\n#{usage()}", 1}}

        rest != [] ->
          {:error, {"Unexpected arguments: #{Enum.join(rest, ", ")}\n\n#{usage()}", 1}}

        missing != [] ->
          {:error, {"Missing required options: #{Enum.join(missing, ", ")}.\n\n#{usage()}", 1}}

        opts[:format] not in [nil, "json", "text"] ->
          {:error, {"Unsupported format: #{opts[:format]}\n\n#{usage()}", 1}}

        true ->
          {:ok,
           %{
             repo: opts[:repo],
             base: opts[:base],
             head: opts[:head],
             format: opts[:format] || "text"
           }}
      end
    end
  end

  defp prepare_workspace(request) do
    case ReviewWorkspace.prepare(request.repo, request.base, request.head) do
      {:ok, workspace} -> {:ok, workspace}
      {:error, message} -> {:error, {message, 1}}
    end
  end

  defp with_runtime(opts, fun) do
    child_opts = [
      config_name: Keyword.get(opts, :config_name, Cerberus.Config),
      config_overrides: Keyword.get(opts, :config_overrides, %{}),
      review_supervisor_name:
        Keyword.get(opts, :review_supervisor_name, Cerberus.ReviewSupervisor),
      task_supervisor_name: Keyword.get(opts, :task_supervisor_name, Cerberus.TaskSupervisor),
      router_name: Keyword.get(opts, :router_name, Cerberus.Router),
      repo_root: Keyword.get(opts, :repo_root, Cerberus.repo_root()),
      router_call_llm: Keyword.get(opts, :router_call_llm)
    ]

    with :ok <- ensure_runtime_dependencies(),
         {:ok, supervisor} <- start_runtime_supervisor(child_opts) do
      runtime = %{
        config: child_opts[:config_name],
        review_supervisor: child_opts[:review_supervisor_name],
        task_supervisor: child_opts[:task_supervisor_name],
        router: child_opts[:router_name],
        assets_root: child_opts[:repo_root]
      }

      try do
        fun.(runtime)
      after
        Supervisor.stop(supervisor)
      end
    else
      {:error, reason} ->
        {:error, {format_runtime_start_error(reason), @runtime_failure_exit_code}}
    end
  end

  defp start_runtime_supervisor(child_opts) do
    previous = Process.flag(:trap_exit, true)

    result =
      try do
        Supervisor.start_link(Cerberus.Application.child_specs(:cli, child_opts),
          strategy: :one_for_one
        )
      after
        Process.flag(:trap_exit, previous)
      end

    receive do
      {:EXIT, _pid, _reason} -> :ok
    after
      0 -> :ok
    end

    case result do
      {:error, reason} -> {:error, reason}
      other -> other
    end
  end

  defp review_workspace(runtime, request, workspace, opts) do
    timeout = Keyword.get(opts, :reviewer_timeout, @default_timeout_ms)

    tool_handler =
      Keyword.get_lazy(opts, :tool_handler, fn ->
        LocalRepoReadHandler.build(workspace.workspace_root)
      end)

    try do
      Review.review(
        workspace.diff,
        build_review_context(request, workspace),
        [
          config_server: runtime.config,
          router_server: runtime.router,
          supervisor: runtime.review_supervisor,
          task_supervisor: runtime.task_supervisor,
          reviewer_timeout: timeout,
          repo_root: runtime.assets_root,
          tool_handler: tool_handler,
          call_llm: Keyword.get(opts, :call_llm, &Cerberus.LLM.OpenRouter.call/1),
          routing_metadata: %{
            repo: workspace.repo_root,
            base_sha: workspace.base_sha,
            head_sha: workspace.head_sha
          }
        ]
        |> maybe_put_keyword(:routing_result, Keyword.get(opts, :routing_result))
      )
    rescue
      e ->
        {:error, {Exception.message(e), @runtime_failure_exit_code}}
    catch
      :exit, reason ->
        {:error, {"CLI review failed: #{inspect(reason)}", @runtime_failure_exit_code}}
    end
  end

  defp build_review_context(request, workspace) do
    %{
      title: "Local change review",
      author: System.get_env("USER") || "local",
      head_branch: request.head,
      base_branch: request.base,
      body: "Review generated from #{workspace.repo_root} for #{request.base}..#{request.head}",
      diff_file: workspace.diff_file,
      repo: workspace.repo_root,
      head_sha: workspace.head_sha,
      base_sha: workspace.base_sha
    }
  end

  defp render_output(result, request, workspace, "json") do
    Jason.encode!(%{
      verdict: result.verdict,
      summary: result.summary,
      findings: Enum.map(result.findings, &finding_to_json/1),
      stats: result.stats,
      refs: refs_to_json(request, workspace),
      planner_trace: Map.get(result, :planner_trace),
      resolved_config: Map.get(result, :resolved_config),
      reviewer_execution_ledger:
        reviewer_execution_ledger_to_json(Map.get(result, :reviewer_results, []))
    })
  end

  defp render_output(result, _request, _workspace, "text") do
    findings =
      case result.findings do
        [] ->
          "- none"

        items ->
          Enum.map_join(items, "\n", &format_text_finding/1)
      end

    """
    Verdict: #{result.verdict}
    Summary: #{result.summary}

    Findings:
    #{findings}
    """
    |> String.trim_trailing()
  end

  defp finding_to_json(%{finding: finding, reviewers: reviewers}) do
    finding
    |> Map.from_struct()
    |> Map.put(:reviewers, reviewers)
  end

  defp finding_to_json(finding) do
    if is_struct(finding), do: Map.from_struct(finding), else: finding
  end

  defp format_text_finding(%{finding: finding, reviewers: reviewers}) do
    label = String.upcase(finding.severity || "info")
    where = if finding.file, do: " `#{finding.file}:#{finding.line || 0}`", else: ""
    sources = if reviewers == [], do: "", else: " (#{Enum.join(reviewers, ", ")})"
    "- #{label} #{finding.title}#{where}#{sources}"
  end

  defp format_text_finding(finding) do
    label = String.upcase(finding.severity || "info")
    where = if finding.file, do: " `#{finding.file}:#{finding.line || 0}`", else: ""
    "- #{label} #{finding.title}#{where}"
  end

  defp print_stdout(output) do
    if String.ends_with?(output, "\n") do
      IO.write(output)
    else
      IO.puts(output)
    end
  end

  defp maybe_halt(code, opts) do
    if Keyword.get(opts, :halt, true) do
      System.halt(code)
    else
      :ok
    end
  end

  defp completed_result(result, request, workspace, format) do
    %{
      output: render_output(result, request, workspace, format),
      exit_code: exit_code_for_verdict(result.verdict),
      verdict: result.verdict
    }
  end

  defp exit_code_for_verdict("FAIL"), do: @blocking_verdict_exit_code
  defp exit_code_for_verdict(_), do: @success_exit_code

  defp format_invalid(invalid) do
    invalid
    |> Enum.map(fn
      {key, nil} -> "--#{key}"
      {key, value} -> "--#{key}=#{value}"
    end)
    |> Enum.join(", ")
  end

  defp missing_required_opts(opts) do
    []
    |> maybe_missing(opts[:repo], "--repo")
    |> maybe_missing(opts[:base], "--base")
    |> maybe_missing(opts[:head], "--head")
  end

  defp maybe_missing(missing, value, flag) when value in [nil, ""], do: missing ++ [flag]
  defp maybe_missing(missing, _value, _flag), do: missing

  defp legacy_diff_option?(argv) do
    Enum.any?(argv, fn arg ->
      arg == "--diff" or arg == "-d" or String.starts_with?(arg, "--diff=")
    end)
  end

  defp legacy_diff_message do
    "Legacy --diff input is no longer supported. Use --repo <path> --base <ref> --head <ref>.\n\n#{usage()}"
  end

  defp no_changes_result(workspace) do
    %{
      verdict: "SKIP",
      summary:
        "No changes to review between #{workspace.base_ref} (#{workspace.base_sha}) and #{workspace.head_ref} (#{workspace.head_sha}).",
      findings: [],
      stats: %{"total" => 0, "pass" => 0, "warn" => 0, "fail" => 0, "skip" => 0},
      planner_trace: nil,
      resolved_config: nil,
      reviewer_results: []
    }
  end

  defp refs_to_json(request, workspace) do
    %{
      repo: workspace.repo_root,
      requested: %{
        base: request.base,
        head: request.head
      },
      resolved: %{
        base: workspace.base_sha,
        head: workspace.head_sha
      }
    }
  end

  defp reviewer_execution_ledger_to_json(results) do
    Enum.map(results, fn result ->
      %{
        reviewer: result.reviewer,
        perspective: result.perspective,
        provider: result.provider,
        model: %{
          id: result.model_id,
          value: result.model
        },
        prompt: %{
          id: result.prompt_id,
          digest: result.prompt_digest
        },
        template: %{
          id: result.template_id,
          digest: result.template_digest
        },
        verdict: result.verdict.verdict,
        status: Atom.to_string(result.status)
      }
    end)
  end

  defp ensure_runtime_dependencies do
    with {:ok, _} <- Application.ensure_all_started(:req),
         {:ok, _} <- Application.ensure_all_started(:telemetry) do
      :ok
    end
  end

  defp normalize_argv(["review" | rest]), do: normalize_argv(rest)
  defp normalize_argv(["--" | rest]), do: normalize_argv(rest)
  defp normalize_argv(argv), do: argv

  defp maybe_put_keyword(opts, _key, nil), do: opts
  defp maybe_put_keyword(opts, key, value), do: Keyword.put(opts, key, value)

  defp format_runtime_start_error(reason) do
    case extract_invalid_config(reason) do
      {:ok, diagnostics} -> Cerberus.Config.format_diagnostics(diagnostics)
      :error -> "Failed to start CLI runtime: #{inspect(reason)}"
    end
  end

  defp extract_invalid_config({:invalid_config, diagnostics}) when is_list(diagnostics),
    do: {:ok, diagnostics}

  defp extract_invalid_config({:shutdown, reason}), do: extract_invalid_config(reason)

  defp extract_invalid_config({:failed_to_start_child, _child, reason}),
    do: extract_invalid_config(reason)

  defp extract_invalid_config({left, right}) do
    case extract_invalid_config(left) do
      {:ok, diagnostics} -> {:ok, diagnostics}
      :error -> extract_invalid_config(right)
    end
  end

  defp extract_invalid_config(reason) when is_list(reason) do
    Enum.find_value(reason, :error, fn item ->
      case extract_invalid_config(item) do
        {:ok, diagnostics} -> {:ok, diagnostics}
        :error -> nil
      end
    end) || :error
  end

  defp extract_invalid_config(_reason), do: :error
end
