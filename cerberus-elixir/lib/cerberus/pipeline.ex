defmodule Cerberus.Pipeline do
  @moduledoc """
  Orchestrates a complete review run: fetch → route → review → aggregate → post.

  Launched asynchronously by the API after `POST /api/reviews`. Updates the
  review run row through its lifecycle (queued → running → completed | failed)
  and posts results to GitHub (verdict comment, PR review, check run).

  ## DI seams (all via `opts`)

      :store           — Store GenServer (default: Cerberus.Store)
      :github_opts     — keyword list forwarded to all GitHub calls (inject :req here)
      :config_server   — Config GenServer (default: Cerberus.Config)
      :router_server   — Router GenServer (default: Cerberus.Router)
      :supervisor      — DynamicSupervisor for reviewers (default: Cerberus.ReviewSupervisor)
      :call_llm        — LLM function passed to each Reviewer
      :tool_handler    — tool handler passed to each Reviewer
      :task_supervisor  — TaskSupervisor for async start (default: Cerberus.TaskSupervisor)
      :reviewer_timeout — per-reviewer timeout in ms (default: 600_000)
      :repo_root       — for template loading
  """

  require Logger

  alias Cerberus.{Config, GitHub, Reviewer, Router, Store, Telemetry}
  alias Cerberus.Verdict.{Aggregator, Cost, Override}

  @tier_to_pool %{flash: :wave1, standard: :wave2, pro: :wave3}
  @default_reviewer_timeout_ms 600_000
  @default_model "openrouter/moonshotai/kimi-k2.5"
  @check_name "Cerberus / Verdict"
  @verdict_marker "<!-- cerberus-verdict -->"

  # --- Public API ---

  @doc "Start the pipeline asynchronously. Returns `{:ok, pid}`."
  def start(review_id, params, opts \\ []) do
    sup = Keyword.get(opts, :task_supervisor, Cerberus.TaskSupervisor)
    Task.Supervisor.start_child(sup, fn -> run(review_id, params, opts) end)
  end

  @doc """
  Execute the full pipeline synchronously.

  Returns `{:ok, aggregated_result}` on success, `{:error, reason}` on failure.
  """
  def run(review_id, params, opts \\ []) do
    store = Keyword.get(opts, :store, Store)
    gh = Keyword.get(opts, :github_opts, [])
    config = Keyword.get(opts, :config_server, Config)
    router = Keyword.get(opts, :router_server, Router)
    supervisor = Keyword.get(opts, :supervisor, Cerberus.ReviewSupervisor)
    timeout = Keyword.get(opts, :reviewer_timeout, @default_reviewer_timeout_ms)

    repo = params.repo
    pr = params.pr_number
    sha = params.head_sha

    try do
      Store.update_review_run(store, review_id, %{status: "running"})

      # 1. Fetch PR context + diff
      {:ok, pr_ctx} = GitHub.fetch_pr_context(repo, pr, gh)
      {:ok, diff} = GitHub.fetch_pr_diff(repo, pr, gh)

      # 2. Check run (best-effort)
      check_id = start_check_run(repo, sha, gh)

      # 3. Route
      {:ok, routing} = Router.route(diff, [metadata: %{repo: repo}], router)

      # 4. Run reviewers in parallel
      results =
        Telemetry.with_review_run(pr, fn otel_ctx ->
          run_panel(routing, pr_ctx, diff, params, config, supervisor, timeout, otel_ctx, opts)
        end)

      # 5. Persist reviewer artifacts
      persist_verdicts(results, review_id, store)
      persist_costs(results, review_id, store)

      # 6. Resolve override
      override = resolve_override(repo, pr, sha, pr_ctx.author, gh)

      # 7. Aggregate
      verdicts = Enum.map(results, & &1.verdict)
      usage = Map.new(results, &{&1.perspective, Map.merge(&1.usage, %{model: &1.model})})
      aggregated = Aggregator.aggregate(verdicts, override: override, usage: usage)

      # 8. Post to GitHub (best-effort)
      post_to_github(repo, pr, sha, aggregated, check_id, gh)

      # 9. Finalize DB
      Store.update_review_run(store, review_id, %{
        status: "completed",
        aggregated_verdict_json: Jason.encode!(to_stored_json(aggregated)),
        completed_at: DateTime.utc_now() |> DateTime.to_iso8601()
      })

      {:ok, aggregated}
    catch
      kind, reason ->
        stacktrace = __STACKTRACE__
        message = Exception.format(kind, reason, stacktrace)
        Logger.error("Pipeline #{review_id} failed: #{message}")

        # Store updates are best-effort — Store GenServer may itself be dead
        try do
          Store.update_review_run(store, review_id, %{status: "failed"})

          Store.insert_event(store, %{
            review_run_id: review_id,
            kind: "pipeline_error",
            payload: %{
              error: Exception.format_banner(kind, reason),
              trace: Exception.format_stacktrace(stacktrace) |> String.slice(0, 4_000)
            }
          })
        catch
          _, _ -> :ok
        end

        {:error, {:pipeline_failed, Exception.format(kind, reason, stacktrace)}}
    end
  end

  # --- Reviewer Dispatch ---

  defp run_panel(routing, pr_ctx, diff, params, config, supervisor, timeout, otel_ctx, opts) do
    diff_file = write_temp_diff(diff)
    task_sup = Keyword.get(opts, :task_supervisor, Cerberus.TaskSupervisor)
    personas = Config.personas(config)
    pool = resolve_model_pool(routing.model_tier, config)

    # Build tool handler from review context unless injected (tests)
    gh = Keyword.get(opts, :github_opts, [])

    opts =
      Keyword.put_new_lazy(opts, :tool_handler, fn ->
        Cerberus.Tools.GithubReadHandler.build(params.repo, params.head_sha, gh)
      end)

    try do
      review_ctx = %{
        title: pr_ctx.title,
        author: pr_ctx.author,
        head_branch: pr_ctx.head_ref,
        base_branch: pr_ctx.base_ref,
        body: pr_ctx.body,
        diff_file: diff_file,
        diff: diff,
        repo: params.repo,
        pr_number: params.pr_number,
        head_sha: params.head_sha
      }

      # Resolve each perspective to its persona once (avoids repeated Config GenServer calls)
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
    after
      File.rm(diff_file)
    end
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
        %{
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
    %{
      reviewer: reviewer,
      perspective: perspective,
      verdict: skip_verdict(reviewer, perspective),
      usage: zero_usage(),
      model: "unknown",
      status: status
    }
  end

  # --- Model Resolution ---

  defp resolve_model_pool(tier, config) do
    pool_tier = Map.get(@tier_to_pool, tier, :wave2)
    Config.model_pool(pool_tier, config)
  end

  defp pick_model(persona, pool) do
    case persona.model_policy do
      :pool ->
        if pool == [], do: @default_model, else: Enum.random(pool)

      model when is_binary(model) and model != "" ->
        model

      _ ->
        @default_model
    end
  end

  # --- Override ---

  defp resolve_override(repo, pr, sha, pr_author, gh) do
    with {:ok, comments} <- GitHub.fetch_comments(repo, pr, gh) do
      comments_with_actor =
        Enum.map(comments, fn c ->
          Map.put(c, "actor", get_in(c, ["user", "login"]) || "unknown")
        end)

      case Override.select(comments_with_actor, sha, :pr_author, pr_author) do
        {:ok, override} -> override
        :none -> nil
      end
    else
      _ -> nil
    end
  end

  # --- Cost ---

  defp persist_verdicts(results, review_id, store) do
    case Store.insert_verdicts(
           store,
           Enum.map(results, fn r ->
             %{
               review_run_id: review_id,
               reviewer: r.reviewer,
               perspective: r.perspective,
               verdict: r.verdict.verdict,
               confidence: r.verdict.confidence,
               summary: r.verdict.summary,
               findings: r.verdict.findings
             }
           end)
         ) do
      :ok ->
        :ok

      {:error, reason} ->
        raise "failed to persist reviewer verdict: #{inspect(reason)}"
    end
  end

  defp persist_costs(results, review_id, store) do
    case Store.insert_costs(
           store,
           Enum.map(results, fn r ->
             cost = Cost.calculate(r.usage.prompt_tokens, r.usage.completion_tokens, r.model)

             %{
               review_run_id: review_id,
               reviewer: r.reviewer,
               model: r.model,
               prompt_tokens: r.usage.prompt_tokens,
               completion_tokens: r.usage.completion_tokens,
               cost_usd: cost,
               duration_ms: 0,
               status: status_label(r.status),
               is_fallback: false
             }
           end)
         ) do
      :ok ->
        :ok

      {:error, reason} ->
        raise "failed to persist reviewer cost: #{inspect(reason)}"
    end
  end

  defp status_label(:ok), do: "success"
  defp status_label(:error), do: "error"
  defp status_label(:timeout), do: "timeout"
  defp status_label(other), do: to_string(other)

  # --- GitHub Posting ---

  defp start_check_run(repo, sha, gh) do
    case GitHub.create_check_run(repo, sha, @check_name, gh ++ [status: "in_progress"]) do
      {:ok, %{body: %{"id" => id}}} -> id
      _ -> nil
    end
  end

  defp post_to_github(repo, pr, sha, aggregated, check_id, gh) do
    # Verdict comment (idempotent upsert)
    body = format_verdict_comment(aggregated)
    GitHub.upsert_comment(repo, pr, @verdict_marker, body, gh)

    # PR review with inline comments
    inline = build_inline_comments(aggregated, repo, pr, gh)
    review_body = "Cerberus: #{aggregated.verdict} — #{aggregated.summary}"
    GitHub.create_pr_review(repo, pr, sha, review_body, inline, gh)

    # Check run conclusion
    if check_id do
      conclusion = verdict_to_conclusion(aggregated.verdict)

      GitHub.update_check_run(
        repo,
        check_id,
        %{
          status: "completed",
          conclusion: conclusion,
          output: %{
            title: "Cerberus: #{aggregated.verdict}",
            summary: aggregated.summary
          }
        },
        gh
      )
    end
  rescue
    e ->
      Logger.warning("GitHub posting failed (non-fatal): #{Exception.message(e)}")
  end

  defp build_inline_comments(aggregated, repo, pr, gh) do
    case GitHub.list_pr_files(repo, pr, gh) do
      {:ok, files} ->
        pos_maps = Map.new(files, &{&1["filename"], GitHub.build_position_map(&1["patch"] || "")})

        aggregated.findings
        |> Enum.flat_map(fn finding ->
          f = extract_finding(finding)

          with %{} = pmap <- Map.get(pos_maps, f.file),
               pos when is_integer(pos) <- Map.get(pmap, f.line) do
            suggestion = if f.suggestion, do: "\n\n> #{f.suggestion}", else: ""

            [
              %{
                path: f.file,
                position: pos,
                body:
                  "**#{String.upcase(f.severity)}**: #{f.title}\n\n#{f.description}#{suggestion}"
              }
            ]
          else
            _ -> []
          end
        end)

      _ ->
        []
    end
  end

  # --- Formatting ---

  defp format_verdict_comment(agg) do
    s = agg.stats

    findings =
      if agg.findings == [] do
        ""
      else
        text =
          agg.findings
          |> Enum.map(&format_one_finding/1)
          |> Enum.join("\n")

        "\n\n### Findings\n\n#{text}"
      end

    override =
      if agg.override,
        do:
          "\n\n> **Override** by `#{agg.override.actor}` for `#{String.slice(agg.override.sha, 0, 7)}`",
        else: ""

    """
    #{@verdict_marker}
    ## #{agg.verdict} — Cerberus

    #{agg.summary}

    | Metric | Count |
    |--------|-------|
    | Reviewers | #{s.total} |
    | Pass | #{s.pass} |
    | Warn | #{s.warn} |
    | Fail | #{s.fail} |
    | Skip | #{s.skip} |
    #{findings}#{override}

    <sub>Cost: $#{Float.round(agg.cost.total_usd, 4)}</sub>
    """
    |> String.trim()
  end

  defp format_one_finding(finding) do
    f = extract_finding(finding)
    reviewers = extract_reviewers(finding)
    badge = String.upcase(f.severity || "?")
    loc = if f.file, do: " `#{f.file}:#{f.line || 0}`", else: ""
    who = if reviewers != [], do: " (#{Enum.join(reviewers, ", ")})", else: ""
    sug = if f.suggestion, do: "\n  > #{f.suggestion}", else: ""
    "- #{badge} **#{f.title}**#{loc}#{who}\n  #{f.description}#{sug}"
  end

  defp extract_finding(%{finding: f}), do: f
  defp extract_finding(f), do: f

  defp extract_reviewers(%{reviewers: r}) when is_list(r), do: r
  defp extract_reviewers(_), do: []

  defp verdict_to_conclusion("PASS"), do: "success"
  defp verdict_to_conclusion("WARN"), do: "neutral"
  defp verdict_to_conclusion("FAIL"), do: "failure"
  defp verdict_to_conclusion("SKIP"), do: "skipped"
  defp verdict_to_conclusion(_), do: "neutral"

  # --- Helpers ---

  defp skip_verdict(reviewer, perspective) do
    %Cerberus.Verdict{
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

  defp write_temp_diff(diff) do
    path =
      Path.join(
        System.tmp_dir!(),
        "cerberus-diff-#{System.unique_integer([:positive])}.diff"
      )

    File.write!(path, diff)
    path
  end

  defp to_stored_json(agg) do
    %{
      verdict: agg.verdict,
      summary: agg.summary,
      stats: agg.stats,
      findings_count: length(agg.findings),
      cost: agg.cost,
      override:
        if(agg.override, do: %{actor: agg.override.actor, sha: agg.override.sha}, else: nil)
    }
  end
end
