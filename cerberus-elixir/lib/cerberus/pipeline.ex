defmodule Cerberus.Pipeline do
  @moduledoc """
  Orchestrates a complete review run: fetch → review → post.

  Launched asynchronously by the API after `POST /api/reviews`. Updates the
  review run row through its lifecycle (queued → running → completed | failed)
  and posts results to GitHub (verdict comment, PR review, check run).

  ## DI seams (all via `opts`)

      :store            — Store GenServer (default: Cerberus.Store)
      :github_opts      — keyword list forwarded to all GitHub calls (inject :req here)
      :config_server    — Config GenServer (default: Cerberus.Config)
      :router_server    — Router GenServer (default: Cerberus.Router)
      :supervisor       — DynamicSupervisor for reviewers (default: Cerberus.ReviewSupervisor)
      :call_llm         — LLM function passed to each Reviewer
      :tool_handler     — tool handler passed to each Reviewer
      :engine           — review execution module (default: Cerberus.Engine)
      :task_supervisor  — TaskSupervisor for async start (default: Cerberus.TaskSupervisor)
      :reviewer_timeout — per-reviewer timeout in ms (default: 600_000)
      :repo_root        — for template loading
  """

  require Logger

  alias Cerberus.{Engine, GitHub, Store}
  alias Cerberus.Verdict.{Cost, Override}

  @check_name "Cerberus / Verdict"
  @verdict_marker "<!-- cerberus-verdict -->"

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
    engine = Keyword.get(opts, :engine, Engine)

    repo = params.repo
    pr = params.pr_number
    sha = params.head_sha

    try do
      Store.update_review_run(store, review_id, %{status: "running"})

      {:ok, pr_ctx} = GitHub.fetch_pr_context(repo, pr, gh)
      {:ok, diff} = GitHub.fetch_pr_diff(repo, pr, gh)

      check_id = start_check_run(repo, sha, gh)
      override = resolve_override(repo, pr, sha, pr_ctx.author, gh)

      {:ok, engine_result} =
        engine.review(
          diff,
          engine_context(pr_ctx, params),
          engine_opts(opts, params, gh, override)
        )

      persist_verdicts(engine_result.reviewer_results, review_id, store)
      persist_costs(engine_result.reviewer_results, review_id, store)

      aggregated = aggregated_result(engine_result)
      post_to_github(repo, pr, sha, aggregated, check_id, gh)

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

  defp engine_context(pr_ctx, params) do
    %{
      title: pr_ctx.title,
      author: pr_ctx.author,
      head_ref: pr_ctx.head_ref,
      base_ref: pr_ctx.base_ref,
      body: pr_ctx.body,
      repo: params.repo,
      pr_number: params.pr_number,
      head_sha: params.head_sha
    }
  end

  defp engine_opts(opts, params, gh, override) do
    opts
    |> Keyword.put_new_lazy(:tool_handler, fn ->
      Cerberus.Tools.GithubReadHandler.build(params.repo, params.head_sha, gh)
    end)
    |> Keyword.put_new(:routing_metadata, %{repo: params.repo})
    |> Keyword.put(:override, override)
  end

  defp aggregated_result(%{reviewer_results: _} = result) do
    result
    |> to_map()
    |> Map.delete(:reviewer_results)
  end

  defp to_map(struct) when is_struct(struct), do: Map.from_struct(struct)
  defp to_map(map) when is_map(map), do: map

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

  defp persist_verdicts(reviewer_results, review_id, store) do
    case Store.insert_verdicts(
           store,
           Enum.map(reviewer_results, fn r ->
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

  defp persist_costs(reviewer_results, review_id, store) do
    case Store.insert_costs(
           store,
           Enum.map(reviewer_results, fn r ->
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

  defp start_check_run(repo, sha, gh) do
    case GitHub.create_check_run(repo, sha, @check_name, gh ++ [status: "in_progress"]) do
      {:ok, %{body: %{"id" => id}}} -> id
      _ -> nil
    end
  end

  defp post_to_github(repo, pr, sha, aggregated, check_id, gh) do
    body = format_verdict_comment(aggregated)
    GitHub.upsert_comment(repo, pr, @verdict_marker, body, gh)

    inline = build_inline_comments(aggregated, repo, pr, gh)
    review_body = "Cerberus: #{aggregated.verdict} — #{aggregated.summary}"
    GitHub.create_pr_review(repo, pr, sha, review_body, inline, gh)

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
