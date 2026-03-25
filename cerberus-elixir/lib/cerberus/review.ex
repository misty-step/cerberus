defmodule Cerberus.Review do
  @moduledoc """
  Shared review execution core for CLI and engine callers.
  """

  require Logger

  alias Cerberus.{Config, Reviewer, Router, Telemetry}
  alias Cerberus.Engine.{Result, ReviewerExecution}
  alias Cerberus.Verdict
  alias Cerberus.Verdict.Aggregator

  @tier_to_pool %{flash: :wave1, standard: :wave2, pro: :wave3}
  @default_reviewer_timeout_ms 600_000
  @default_model "openrouter/moonshotai/kimi-k2.5"

  @spec review(String.t(), map(), keyword()) :: {:ok, Result.t()}
  def review(diff, context, opts \\ []) when is_binary(diff) and is_map(context) do
    override = Keyword.get(opts, :override)

    reviewer_results =
      Telemetry.with_review_run(Map.get(context, :pr_number, 0), fn otel_ctx ->
        routing = resolve_routing!(diff, context, opts)
        run_panel(routing, context, diff, otel_ctx, opts)
      end)

    aggregated =
      Aggregator.aggregate(
        Enum.map(reviewer_results, & &1.verdict),
        override: override,
        usage: usage_by_reviewer(reviewer_results)
      )

    {:ok, aggregated |> Map.put(:reviewer_results, reviewer_results) |> then(&struct(Result, &1))}
  end

  defp usage_by_reviewer(reviewer_results) do
    Map.new(reviewer_results, fn result ->
      {result.reviewer, Map.merge(result.usage, %{model: result.model})}
    end)
  end

  defp resolve_routing!(diff, context, opts) do
    case Keyword.fetch(opts, :routing_result) do
      {:ok, routing} ->
        routing

      :error ->
        router = Keyword.get(opts, :router_server, Router)
        routing_metadata = Keyword.get(opts, :routing_metadata, default_routing_metadata(context))

        try do
          case Router.route(diff, [metadata: routing_metadata], router) do
            {:ok, routing} -> routing
            {:error, reason} -> raise RuntimeError, "Routing failed: #{inspect(reason)}"
          end
        catch
          :exit, reason ->
            raise RuntimeError, "Routing failed: #{inspect(reason)}"
        end
    end
  end

  defp default_routing_metadata(context) do
    %{}
    |> maybe_put(:repo, Map.get(context, :repo))
    |> maybe_put(:base_sha, Map.get(context, :base_sha))
    |> maybe_put(:head_sha, Map.get(context, :head_sha))
  end

  defp run_panel(routing, context, diff, otel_ctx, opts) do
    config = Keyword.get(opts, :config_server, Config)
    supervisor = Keyword.get(opts, :supervisor, Cerberus.ReviewSupervisor)
    timeout = Keyword.get(opts, :reviewer_timeout, @default_reviewer_timeout_ms)
    task_sup = Keyword.get(opts, :task_supervisor, Cerberus.TaskSupervisor)

    with_diff_file(context, diff, fn review_ctx ->
      personas = Config.personas(config)
      pool = resolve_model_pool(routing.model_tier, config)

      panel =
        Enum.map(routing.panel, fn perspective ->
          persona = Enum.find(personas, &(to_string(&1.perspective) == perspective))

          unless persona do
            known = Enum.map(personas, &to_string(&1.perspective))

            raise ArgumentError,
                  "unknown perspective: #{inspect(perspective)} (known: #{inspect(known)})"
          end

          model = pick_model(persona, pool)
          {persona.name, perspective, persona, model}
        end)

      tasks =
        Enum.map(panel, fn {_reviewer, perspective, persona, model} ->
          Task.Supervisor.async_nolink(task_sup, fn ->
            Telemetry.with_reviewer(otel_ctx, perspective, model, fn ->
              spawn_reviewer(persona, model, review_ctx, supervisor, timeout, opts)
            end)
          end)
        end)

      tasks
      |> Enum.zip(panel)
      |> Enum.map(fn {task, {reviewer, perspective, _persona, _model}} ->
        collect_result(task, reviewer, perspective, timeout)
      end)
    end)
  end

  defp with_diff_file(context, diff, fun) do
    case Map.get(context, :diff_file) do
      diff_file when is_binary(diff_file) ->
        fun.(build_review_context(context, diff, diff_file))

      _ ->
        diff_file = write_temp_diff(diff)

        try do
          fun.(build_review_context(context, diff, diff_file))
        after
          File.rm(diff_file)
        end
    end
  end

  defp build_review_context(context, diff, diff_file) do
    %{
      title: Map.get(context, :title),
      author: Map.get(context, :author),
      head_branch: Map.get(context, :head_branch) || Map.get(context, :head_ref),
      base_branch: Map.get(context, :base_branch) || Map.get(context, :base_ref),
      body: Map.get(context, :body),
      diff_file: diff_file,
      diff: diff,
      repo: Map.get(context, :repo),
      pr_number: Map.get(context, :pr_number),
      head_sha: Map.get(context, :head_sha),
      project_context: Map.get(context, :project_context)
    }
  end

  defp spawn_reviewer(persona, model, review_ctx, supervisor, timeout, opts) do
    reviewer_opts =
      [
        perspective: persona.perspective,
        model: model,
        config_server: Keyword.get(opts, :config_server, Config),
        timeout_ms: timeout
      ] ++ Keyword.take(opts, [:call_llm, :tool_handler, :repo_root])

    {:ok, pid} = DynamicSupervisor.start_child(supervisor, {Reviewer, reviewer_opts})

    try do
      Reviewer.review(pid, review_ctx, timeout)
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
      {:ok, {:ok, result}} ->
        %ReviewerExecution{
          reviewer: reviewer,
          perspective: perspective,
          verdict: %{result.verdict | reviewer: reviewer, perspective: perspective},
          usage: result.usage,
          model: result[:model] || "unknown",
          status: :ok
        }

      {:ok, {:error, reason}} ->
        Logger.warning("Reviewer #{perspective} failed: #{inspect(reason)}")
        degraded_result(reviewer, perspective, :error)

      {:exit, reason} ->
        Logger.warning("Reviewer #{perspective} crashed: #{inspect(reason)}")
        degraded_result(reviewer, perspective, :error)

      nil ->
        Logger.warning("Reviewer #{perspective} timed out")
        degraded_result(reviewer, perspective, :timeout)
    end
  end

  defp degraded_result(reviewer, perspective, status) do
    %ReviewerExecution{
      reviewer: reviewer,
      perspective: perspective,
      verdict: skip_verdict(reviewer, perspective),
      usage: %{prompt_tokens: 0, completion_tokens: 0},
      model: "unknown",
      status: status
    }
  end

  defp resolve_model_pool(tier, config) do
    pool_tier = Map.get(@tier_to_pool, tier, :wave2)
    Config.model_pool(pool_tier, config)
  end

  defp pick_model(persona, pool) do
    case persona.model_policy do
      :pool -> List.first(pool) || @default_model
      model when is_binary(model) and model != "" -> model
      _ -> @default_model
    end
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

  defp write_temp_diff(diff) do
    path =
      Path.join(
        System.tmp_dir!(),
        "cerberus-diff-#{System.unique_integer([:positive])}.diff"
      )

    File.write!(path, diff)
    path
  end

  defp maybe_put(map, _key, nil), do: map
  defp maybe_put(map, key, value), do: Map.put(map, key, value)
end
