defmodule Cerberus.CLI do
  @moduledoc """
  Local ref-range review entrypoint shared by the mix task and release wrapper.
  """

  alias Cerberus.{Config, Reviewer, ReviewWorkspace}
  alias Cerberus.Tools.LocalRepoReadHandler
  alias Cerberus.Verdict
  alias Cerberus.Verdict.Aggregator

  @switches [repo: :string, base: :string, head: :string, format: :string, help: :boolean]
  @aliases [r: :repo, b: :base, f: :format, h: :help]
  @tier_to_pool %{flash: :wave1, standard: :wave2, pro: :wave3}
  @default_timeout_ms 600_000
  @default_model "openrouter/moonshotai/kimi-k2.5"

  @spec run([String.t()], keyword()) :: {:ok, String.t()} | {:error, {String.t(), pos_integer()}}
  def run(argv, opts \\ []) do
    opts = Keyword.merge(Application.get_env(:cerberus_elixir, :cli_overrides, []), opts)
    argv = normalize_argv(argv)

    with {:ok, request} <- parse_args(argv),
         {:ok, workspace} <- prepare_workspace(request) do
      try do
        if workspace.no_changes? do
          {:ok, render_output(no_changes_result(workspace), request.format)}
        else
          with {:ok, aggregated} <-
                 with_runtime(opts, &review_workspace(&1, request, workspace, opts)) do
            {:ok, render_output(aggregated, request.format)}
          end
        end
      after
        ReviewWorkspace.cleanup(workspace)
      end
    end
  end

  @spec main([String.t()], keyword()) :: :ok | {:error, String.t()}
  def main(argv \\ System.argv(), opts \\ []) do
    case run(argv, opts) do
      {:ok, output} ->
        print_stdout(output)
        maybe_halt(0, opts)
        :ok

      {:error, {message, code}} ->
        IO.puts(:stderr, message)
        maybe_halt(code, opts)
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
        {:error, {"Failed to start CLI runtime: #{inspect(reason)}", 1}}
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
    routing =
      case Keyword.get(opts, :routing_result) do
        nil ->
          route_diff(workspace.diff, runtime.router, workspace)

        result ->
          result
      end

    case routing do
      {:error, _} = error ->
        error

      %{} = routing_result ->
        run_panel(runtime, request, workspace, routing_result, opts)
    end
  end

  defp run_panel(runtime, request, workspace, routing, opts) do
    personas = Config.personas(runtime.config)
    model_pool = resolve_model_pool(routing.model_tier, runtime.config)
    timeout = Keyword.get(opts, :reviewer_timeout, @default_timeout_ms)

    tool_handler =
      Keyword.get_lazy(opts, :tool_handler, fn ->
        LocalRepoReadHandler.build(workspace.workspace_root)
      end)

    panel =
      Enum.map(routing.panel, fn perspective ->
        persona =
          Enum.find(personas, &(to_string(&1.perspective) == perspective)) ||
            raise ArgumentError, "unknown perspective: #{inspect(perspective)}"

        model = pick_model(persona, model_pool)
        {persona.name, perspective, persona, model}
      end)

    tasks =
      Enum.map(panel, fn {_reviewer, _perspective, persona, model} ->
        Task.Supervisor.async_nolink(runtime.task_supervisor, fn ->
          review_one(persona, model, request, workspace, runtime, opts, timeout, tool_handler)
        end)
      end)

    results =
      tasks
      |> Enum.zip(panel)
      |> Enum.map(fn {task, {reviewer, perspective, _persona, _model}} ->
        collect_result(task, reviewer, perspective, timeout)
      end)

    verdicts = Enum.map(results, & &1.verdict)
    usage = Map.new(results, &{&1.reviewer, Map.merge(&1.usage, %{model: &1.model})})

    {:ok, Aggregator.aggregate(verdicts, usage: usage)}
  rescue
    e ->
      {:error, {"CLI review failed: #{Exception.message(e)}", 1}}
  end

  defp route_diff(diff_text, router, workspace) do
    metadata = %{
      repo: workspace.repo_root,
      base_sha: workspace.base_sha,
      head_sha: workspace.head_sha
    }

    try do
      case Cerberus.Router.route(diff_text, [metadata: metadata], router) do
        {:ok, result} -> result
        {:error, reason} -> {:error, {"Routing failed: #{inspect(reason)}", 1}}
      end
    catch
      :exit, reason ->
        {:error, {"Routing failed: #{inspect(reason)}", 1}}
    end
  end

  defp review_one(persona, model, request, workspace, runtime, opts, timeout, tool_handler) do
    reviewer_opts =
      [
        perspective: persona.perspective,
        model: model,
        config_server: runtime.config,
        timeout_ms: timeout,
        call_llm: Keyword.get(opts, :call_llm, &Cerberus.LLM.OpenRouter.call/1),
        tool_handler: tool_handler,
        repo_root: runtime.assets_root
      ]

    {:ok, pid} =
      DynamicSupervisor.start_child(runtime.review_supervisor, {Reviewer, reviewer_opts})

    try do
      review_context = %{
        title: "Local change review",
        author: System.get_env("USER") || "local",
        head_branch: request.head,
        base_branch: request.base,
        body: "Review generated from #{workspace.repo_root} for #{request.base}..#{request.head}",
        diff_file: workspace.diff_file
      }

      Reviewer.review(pid, review_context, timeout)
    after
      try do
        GenServer.stop(pid, :normal, 5_000)
      catch
        :exit, _ -> :ok
      end
    end
  end

  defp collect_result(task, reviewer, perspective, timeout) do
    case Task.yield(task, timeout + 5_000) || Task.shutdown(task) do
      {:ok, {:ok, %{verdict: verdict, usage: usage} = result}} ->
        %{
          reviewer: reviewer,
          perspective: perspective,
          verdict: verdict,
          usage: usage,
          model: Map.get(result, :model, "unknown")
        }

      {:ok, {:error, _reason}} ->
        degraded_result(reviewer, perspective)

      {:exit, _reason} ->
        degraded_result(reviewer, perspective)

      nil ->
        degraded_result(reviewer, perspective)
    end
  end

  defp degraded_result(reviewer, perspective) do
    %{
      reviewer: reviewer,
      perspective: perspective,
      verdict: skip_verdict(reviewer, perspective),
      usage: zero_usage(),
      model: "unknown"
    }
  end

  defp skip_verdict(reviewer, perspective) do
    %Verdict{
      reviewer: reviewer,
      perspective: perspective,
      verdict: "SKIP",
      confidence: 0.0,
      summary: "Reviewer did not complete",
      findings: [],
      stats: %{
        "files_reviewed" => 0,
        "files_with_issues" => 0,
        "critical" => 0,
        "major" => 0,
        "minor" => 0,
        "info" => 0
      }
    }
  end

  defp zero_usage, do: %{prompt_tokens: 0, completion_tokens: 0}

  defp resolve_model_pool(tier, config) do
    pool_tier = Map.get(@tier_to_pool, tier, :wave2)
    Config.model_pool(pool_tier, config)
  end

  defp pick_model(persona, pool) do
    case persona.model_policy do
      :pool -> List.first(pool) || @default_model
      model when is_binary(model) -> model
      _ -> @default_model
    end
  end

  defp render_output(result, "json") do
    Jason.encode!(%{
      verdict: result.verdict,
      summary: result.summary,
      findings: Enum.map(result.findings, &finding_to_json/1),
      stats: result.stats
    })
  end

  defp render_output(result, "text") do
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
      stats: %{"total" => 0, "pass" => 0, "warn" => 0, "fail" => 0, "skip" => 0}
    }
  end

  defp ensure_runtime_dependencies do
    case Application.ensure_all_started(:telemetry) do
      {:ok, _started} -> :ok
      {:error, reason} -> {:error, reason}
    end
  end

  defp normalize_argv(["review" | rest]), do: normalize_argv(rest)
  defp normalize_argv(["--" | rest]), do: normalize_argv(rest)
  defp normalize_argv(argv), do: argv

  defp usage do
    """
    Usage:
      mix cerberus.review --repo <path> --base <ref> --head <ref> [--format json|text]
      bin/cerberus review --repo <path> --base <ref> --head <ref> [--format json|text]
    """
    |> String.trim_trailing()
  end
end
