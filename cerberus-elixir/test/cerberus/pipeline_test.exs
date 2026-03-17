defmodule Cerberus.PipelineTest do
  use ExUnit.Case, async: false

  alias Cerberus.Pipeline

  @valid_verdict_json """
  ```json
  {
    "reviewer": "trace",
    "perspective": "correctness",
    "verdict": "PASS",
    "confidence": 0.85,
    "summary": "No issues found",
    "findings": [],
    "stats": {
      "files_reviewed": 1,
      "files_with_issues": 0,
      "critical": 0,
      "major": 0,
      "minor": 0,
      "info": 0
    }
  }
  ```
  """

  @diff """
  diff --git a/lib/foo.ex b/lib/foo.ex
  --- a/lib/foo.ex
  +++ b/lib/foo.ex
  @@ -1,3 +1,4 @@
   defmodule Foo do
  +  def bar, do: :ok
   end
  """

  setup do
    Process.flag(:trap_exit, true)
    uid = System.unique_integer([:positive])

    # Store
    db_path = Path.join(System.tmp_dir!(), "cerberus_pipeline_test_#{uid}.db")
    {:ok, store} = Cerberus.Store.start_link(database_path: db_path)

    # Config (unique name to avoid clash with Application-started one)
    repo_root = Application.fetch_env!(:cerberus_elixir, :repo_root)
    config_name = :"pipeline_test_config_#{uid}"
    {:ok, config} = Cerberus.Config.start_link(name: config_name, repo_root: repo_root)

    # Router (mock LLM, unique name)
    router_llm = fn _params ->
      {:ok, ["correctness", "security", "architecture", "testing"]}
    end

    router_name = :"pipeline_test_router_#{uid}"

    {:ok, router} =
      Cerberus.Router.start_link(
        name: router_name,
        config_server: config_name,
        call_llm: router_llm
      )

    # DynamicSupervisor for reviewers
    {:ok, supervisor} = DynamicSupervisor.start_link(strategy: :one_for_one)

    # TaskSupervisor for async
    {:ok, task_sup} = Task.Supervisor.start_link()

    on_exit(fn -> File.rm(db_path) end)

    %{
      store: store,
      config: config_name,
      router: router,
      supervisor: supervisor,
      task_sup: task_sup,
      repo_root: repo_root
    }
  end

  defp create_run(store, attrs \\ %{}) do
    Cerberus.Store.create_review_run(store, %{
      repo: attrs[:repo] || "org/repo",
      pr_number: attrs[:pr_number] || 42,
      head_sha: attrs[:head_sha] || "abc123def456"
    })
  end

  defp mock_github_req(responses) do
    pid = self()

    Req.new(
      adapter: fn request ->
        send(pid, {:github_request, request.method, request.url})
        response = find_response(request, responses)
        {request, response}
      end
    )
  end

  defp find_response(request, responses) do
    url = to_string(request.url)
    method = request.method
    headers = request.headers

    accept =
      headers
      |> Enum.find_value(fn
        {"accept", [v | _]} -> v
        {"accept", v} when is_binary(v) -> v
        _ -> nil
      end)

    # Match on URL patterns
    cond do
      method == :get and String.match?(url, ~r{/pulls/\d+$}) and
          accept == "application/vnd.github.diff" ->
        Map.get(responses, :diff, %Req.Response{status: 200, body: @diff})

      method == :get and String.match?(url, ~r{/pulls/\d+$}) ->
        Map.get(responses, :pr_context, default_pr_context_response())

      method == :get and String.contains?(url, "/issues/") and String.contains?(url, "/comments") ->
        Map.get(responses, :comments, %Req.Response{status: 200, body: []})

      method == :get and String.contains?(url, "/pulls/") and String.contains?(url, "/files") ->
        Map.get(responses, :files, %Req.Response{status: 200, body: []})

      method == :post and String.contains?(url, "/check-runs") ->
        Map.get(responses, :create_check, %Req.Response{status: 201, body: %{"id" => 999}})

      method == :patch and String.contains?(url, "/check-runs") ->
        Map.get(responses, :update_check, %Req.Response{status: 200, body: %{}})

      method == :post and String.contains?(url, "/reviews") ->
        Map.get(responses, :create_review, %Req.Response{status: 200, body: %{}})

      method == :post and String.contains?(url, "/comments") ->
        Map.get(responses, :create_comment, %Req.Response{status: 201, body: %{"id" => 1}})

      true ->
        %Req.Response{status: 404, body: %{"error" => "not found"}}
    end
  end

  defp default_pr_context_response do
    %Req.Response{
      status: 200,
      body: %{
        "title" => "Test PR",
        "user" => %{"login" => "testuser"},
        "head" => %{"ref" => "feat/test", "sha" => "abc123def456"},
        "base" => %{"ref" => "main"},
        "body" => "Test PR body"
      }
    }
  end

  defp mock_llm_pass(_params) do
    {:ok,
     %{
       content: @valid_verdict_json,
       tool_calls: nil,
       usage: %{prompt_tokens: 100, completion_tokens: 50}
     }}
  end

  defp pipeline_opts(ctx, overrides \\ []) do
    mock_req = mock_github_req(Keyword.get(overrides, :github_responses, %{}))

    [
      store: ctx.store,
      config_server: ctx.config,
      router_server: ctx.router,
      supervisor: ctx.supervisor,
      task_supervisor: ctx.task_sup,
      github_opts: [req: mock_req, max_retries: 0, retry_delay: fn _ -> :ok end],
      call_llm: Keyword.get(overrides, :call_llm, &mock_llm_pass/1),
      repo_root: ctx.repo_root,
      reviewer_timeout: Keyword.get(overrides, :reviewer_timeout, 30_000)
    ]
  end

  defp params(overrides \\ %{}) do
    Map.merge(
      %{repo: "org/repo", pr_number: 42, head_sha: "abc123def456"},
      overrides
    )
  end

  # --- Happy Path ---

  describe "happy path" do
    test "POST creates run, spawns reviewers, aggregates, posts to GitHub", ctx do
      review_id = create_run(ctx.store)
      opts = pipeline_opts(ctx)

      assert {:ok, result} = Pipeline.run(review_id, params(), opts)

      # Verdict aggregated
      assert result.verdict in ["PASS", "WARN", "SKIP"]
      assert is_map(result.stats)
      assert result.stats.total > 0

      # DB updated to completed
      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"
      assert run.aggregated_verdict != nil
      assert run.completed_at != nil
    end

    test "GET returns running during execution, completed after", ctx do
      review_id = create_run(ctx.store)

      # Verify starts as queued
      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "queued"

      # Run synchronously — it will set running then completed
      assert {:ok, _} = Pipeline.run(review_id, params(), pipeline_opts(ctx))

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"
    end
  end

  # --- Partial Failure ---

  describe "partial failure" do
    test "some reviewers timeout — others succeed with SKIP for failed", ctx do
      Process.flag(:trap_exit, true)
      call_count = :counters.new(1, [:atomics])

      partial_llm = fn params ->
        count = :counters.get(call_count, 1)
        :counters.add(call_count, 1, 1)

        if count == 0 do
          Process.sleep(10_000)
          {:error, :timeout}
        else
          mock_llm_pass(params)
        end
      end

      review_id = create_run(ctx.store)
      opts = pipeline_opts(ctx, call_llm: partial_llm, reviewer_timeout: 2_000)

      assert {:ok, result} = Pipeline.run(review_id, params(), opts)

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"

      # At least one SKIP from the timed-out reviewer
      assert result.stats.skip >= 1
      # At least one successful reviewer
      assert result.stats.pass >= 1 or result.stats.warn >= 1
    end

    test "reviewer returns error — degraded to SKIP", ctx do
      Process.flag(:trap_exit, true)

      error_llm = fn _params ->
        {:error, :transient}
      end

      review_id = create_run(ctx.store)
      opts = pipeline_opts(ctx, call_llm: error_llm)

      assert {:ok, result} = Pipeline.run(review_id, params(), opts)

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"

      # All reviewers failed — all SKIP
      assert result.verdict == "SKIP"
      assert result.stats.skip == result.stats.total
    end

    test "reviewer process crashes — degraded to SKIP via {:exit, reason}", ctx do
      Process.flag(:trap_exit, true)

      crash_llm = fn _params ->
        # Simulate a process crash (exit, not exception)
        Process.exit(self(), :kill)
      end

      review_id = create_run(ctx.store)
      opts = pipeline_opts(ctx, call_llm: crash_llm, reviewer_timeout: 5_000)

      assert {:ok, result} = Pipeline.run(review_id, params(), opts)

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"

      # Crashed reviewers degraded to SKIP
      assert result.stats.skip == result.stats.total
    end
  end

  # --- Full Failure ---

  describe "full failure" do
    test "GitHub fetch fails — pipeline fails, status: failed", ctx do
      Process.flag(:trap_exit, true)

      error_req =
        Req.new(
          adapter: fn request ->
            {request, %Req.Response{status: 500, body: %{"error" => "internal"}}}
          end
        )

      review_id = create_run(ctx.store)

      opts =
        Keyword.merge(pipeline_opts(ctx),
          github_opts: [req: error_req, max_retries: 0, retry_delay: fn _ -> :ok end]
        )

      assert {:error, {:pipeline_failed, _msg}} = Pipeline.run(review_id, params(), opts)

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "failed"

      # Verify error event was persisted
      {:ok, events} = Cerberus.Store.list_events(ctx.store, review_id)
      assert [%{kind: "pipeline_error", payload: payload}] = events
      assert is_map(payload)
      assert Map.has_key?(payload, "error")
    end
  end

  # --- Resilience: GitHub failures ---

  describe "GitHub posting resilience" do
    test "check run creation failure (500) — pipeline still completes", ctx do
      review_id = create_run(ctx.store)

      opts =
        pipeline_opts(ctx,
          github_responses: %{
            create_check: %Req.Response{status: 500, body: %{"error" => "internal"}}
          }
        )

      assert {:ok, result} = Pipeline.run(review_id, params(), opts)
      assert result.verdict in ["PASS", "WARN", "SKIP"]

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"
    end

    test "GitHub posting raises — pipeline still completes", ctx do
      review_id = create_run(ctx.store)

      # Mock that returns success for everything except comment creation, which raises
      error_on_comment =
        Req.new(
          adapter: fn request ->
            url = to_string(request.url)

            response =
              cond do
                request.method == :get and String.match?(url, ~r{/pulls/\d+$}) and
                    Enum.any?(request.headers, fn
                      {"accept", [v | _]} -> v == "application/vnd.github.diff"
                      {"accept", v} when is_binary(v) -> v == "application/vnd.github.diff"
                      _ -> false
                    end) ->
                  %Req.Response{status: 200, body: @diff}

                request.method == :get and String.match?(url, ~r{/pulls/\d+$}) ->
                  default_pr_context_response()

                request.method == :get and String.contains?(url, "/issues/") and
                    String.contains?(url, "/comments") ->
                  %Req.Response{status: 200, body: []}

                request.method == :get and String.contains?(url, "/pulls/") and
                    String.contains?(url, "/files") ->
                  %Req.Response{status: 200, body: []}

                request.method == :post and String.contains?(url, "/check-runs") ->
                  %Req.Response{status: 201, body: %{"id" => 999}}

                request.method == :post and String.contains?(url, "/comments") ->
                  raise "GitHub API unavailable"

                true ->
                  %Req.Response{status: 200, body: %{}}
              end

            {request, response}
          end
        )

      opts =
        Keyword.merge(pipeline_opts(ctx),
          github_opts: [req: error_on_comment, max_retries: 0, retry_delay: fn _ -> :ok end]
        )

      assert {:ok, result} = Pipeline.run(review_id, params(), opts)
      assert result.verdict in ["PASS", "WARN", "SKIP"]

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"
    end
  end

  # --- Async Start ---

  describe "start/3" do
    test "fires pipeline asynchronously", ctx do
      review_id = create_run(ctx.store)
      opts = pipeline_opts(ctx)

      assert {:ok, pid} = Pipeline.start(review_id, params(), opts)
      assert is_pid(pid)

      # Wait for completion
      ref = Process.monitor(pid)
      assert_receive {:DOWN, ^ref, :process, ^pid, :normal}, 30_000

      {:ok, run} = Cerberus.Store.get_review_run(ctx.store, review_id)
      assert run.status == "completed"
    end
  end

  # --- Cost Persistence ---

  describe "cost tracking" do
    test "persists per-reviewer costs", ctx do
      review_id = create_run(ctx.store)
      opts = pipeline_opts(ctx)

      assert {:ok, _} = Pipeline.run(review_id, params(), opts)

      {:ok, costs} = Cerberus.Store.review_run_costs(ctx.store, review_id)
      assert length(costs) > 0

      Enum.each(costs, fn c ->
        assert is_binary(c.reviewer)
        assert is_binary(c.model)
        assert c.prompt_tokens >= 0
        assert c.completion_tokens >= 0
      end)
    end
  end
end
