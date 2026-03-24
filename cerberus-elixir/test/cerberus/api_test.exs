defmodule Cerberus.APITest do
  use ExUnit.Case, async: false
  import Plug.Test
  import Plug.Conn

  alias Cerberus.{API, Pipeline}

  @api_key "test-cerberus-api-key"
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
    uid = System.unique_integer([:positive])
    db_path = Path.join(System.tmp_dir!(), "cerberus_api_test_#{uid}.db")
    {:ok, store} = Cerberus.Store.start_link(database_path: db_path)

    repo_root = Application.fetch_env!(:cerberus_elixir, :repo_root)
    config_name = :"api_test_config_#{uid}"
    {:ok, _config} = Cerberus.Config.start_link(name: config_name, repo_root: repo_root)

    :sys.replace_state(config_name, fn state ->
      correctness_persona =
        Enum.find(state.personas, fn persona -> persona.perspective == :correctness end)

      %{
        state
        | personas: [correctness_persona],
          routing: %{
            state.routing
            | panel_size: 1,
              fallback_panel: ["correctness"],
              always_include: [],
              include_if_code_changed: []
          }
      }
    end)

    router_llm = fn _params ->
      {:ok, ["correctness"]}
    end

    router_name = :"api_test_router_#{uid}"

    {:ok, router} =
      Cerberus.Router.start_link(
        name: router_name,
        config_server: config_name,
        call_llm: router_llm
      )

    {:ok, supervisor} = DynamicSupervisor.start_link(strategy: :one_for_one)
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

  defp call(conn, store, api_opts \\ []) do
    API.call(conn, API.init([api_key: @api_key, store: store] ++ api_opts))
  end

  defp json_post(path, body, store, api_opts \\ []) do
    conn(:post, path, Jason.encode!(body))
    |> put_req_header("content-type", "application/json")
    |> put_req_header("authorization", "Bearer #{@api_key}")
    |> call(store, api_opts)
  end

  defp authed_get(path, store) do
    conn(:get, path)
    |> put_req_header("authorization", "Bearer #{@api_key}")
    |> call(store)
  end

  defp mock_github_req(responses, pid \\ self()) do
    Req.new(
      adapter: fn request ->
        send(
          pid,
          {:github_request, request.method, request.url, authorization_header(request.headers)}
        )

        {request, find_response(request, responses)}
      end
    )
  end

  defp authorization_header(headers) do
    Enum.find_value(headers, fn
      {"authorization", [value | _]} -> value
      {"authorization", value} when is_binary(value) -> value
      _ -> nil
    end)
  end

  defp find_response(request, responses) do
    url = to_string(request.url)
    method = request.method
    headers = request.headers

    accept =
      headers
      |> Enum.find_value(fn
        {"accept", [value | _]} -> value
        {"accept", value} when is_binary(value) -> value
        _ -> nil
      end)

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

  defp pipeline_opts(ctx, overrides) do
    opts = [
      store: ctx.store,
      config_server: ctx.config,
      router_server: ctx.router,
      supervisor: ctx.supervisor,
      task_supervisor: ctx.task_sup,
      github_opts: [req: mock_github_req(Keyword.get(overrides, :github_responses, %{}))],
      call_llm: Keyword.fetch!(overrides, :call_llm),
      repo_root: ctx.repo_root,
      reviewer_timeout: Keyword.get(overrides, :reviewer_timeout, 5_000)
    ]

    case Keyword.fetch(overrides, :github_req_builder) do
      {:ok, builder} -> opts ++ [github_req_builder: builder]
      :error -> opts
    end
  end

  defp pass_llm(_params) do
    {:ok,
     %{
       content: @valid_verdict_json,
       tool_calls: nil,
       usage: %{prompt_tokens: 100, completion_tokens: 50}
     }}
  end

  defp async_pipeline_fn(test_pid, ctx, overrides) do
    opts = pipeline_opts(ctx, Keyword.put_new(overrides, :call_llm, &pass_llm/1))

    fn review_id, params ->
      spawn(fn ->
        result = Pipeline.run(review_id, params, opts)
        send(test_pid, {:pipeline_finished, review_id, result})
      end)
    end
  end

  defp collect_github_auth_headers(acc \\ []) do
    receive do
      {:github_request, _method, _url, auth_header} ->
        collect_github_auth_headers([auth_header | acc])
    after
      50 -> Enum.reverse(acc)
    end
  end

  defp with_env(var, value, fun) do
    previous = System.get_env(var)

    if value do
      System.put_env(var, value)
    else
      System.delete_env(var)
    end

    try do
      fun.()
    after
      if previous do
        System.put_env(var, previous)
      else
        System.delete_env(var)
      end
    end
  end

  defp wait_for_status(store, review_id, expected, attempts \\ 50)

  defp wait_for_status(_store, review_id, expected, 0) do
    flunk("timed out waiting for review #{review_id} to reach status #{expected}")
  end

  defp wait_for_status(store, review_id, expected, attempts) do
    conn = authed_get("/api/reviews/#{review_id}", store)
    assert conn.status == 200
    body = Jason.decode!(conn.resp_body)

    if body["status"] == expected do
      body
    else
      Process.sleep(20)
      wait_for_status(store, review_id, expected, attempts - 1)
    end
  end

  # --- Authentication ---

  describe "authentication" do
    test "rejects unauthenticated non-health requests", %{store: store} do
      conn = conn(:get, "/api/reviews/1") |> call(store)
      assert conn.status == 401
      body = Jason.decode!(conn.resp_body)
      assert body["error"] == "missing_or_invalid_auth"
    end

    test "rejects requests with wrong token", %{store: store} do
      conn =
        conn(:get, "/api/reviews/1")
        |> put_req_header("authorization", "Bearer wrong-key")
        |> call(store)

      assert conn.status == 401
    end

    test "accepts valid bearer token", %{store: store} do
      conn = authed_get("/api/health", store)
      assert conn.status == 200
    end

    test "health check bypasses auth", %{store: store} do
      conn = conn(:get, "/api/health") |> call(store)
      assert conn.status == 200
      body = Jason.decode!(conn.resp_body)
      assert body["status"] == "ok"
    end
  end

  # --- Health ---

  describe "GET /api/health" do
    test "returns ok with status", %{store: store} do
      conn = authed_get("/api/health", store)
      assert conn.status == 200
      body = Jason.decode!(conn.resp_body)
      assert body["status"] == "ok"
    end
  end

  # --- POST /api/reviews ---

  describe "POST /api/reviews" do
    test "rejects missing required fields", %{store: store} do
      conn = json_post("/api/reviews", %{}, store)
      assert conn.status == 422
      body = Jason.decode!(conn.resp_body)
      assert body["error"] =~ "missing"
    end

    test "rejects missing repo", %{store: store} do
      conn = json_post("/api/reviews", %{pr_number: 1, head_sha: "abc123"}, store)
      assert conn.status == 422
    end

    test "rejects empty string repo", %{store: store} do
      conn = json_post("/api/reviews", %{repo: "", pr_number: 1, head_sha: "abc123"}, store)
      assert conn.status == 422
    end

    test "rejects empty string head_sha", %{store: store} do
      conn = json_post("/api/reviews", %{repo: "org/repo", pr_number: 1, head_sha: ""}, store)
      assert conn.status == 422
    end

    test "rejects non-integer pr_number", %{store: store} do
      conn =
        json_post(
          "/api/reviews",
          %{repo: "org/repo", pr_number: "abc", head_sha: "abc123"},
          store
        )

      assert conn.status == 422
    end

    test "accepts valid review request and returns 202", %{store: store} do
      conn =
        json_post(
          "/api/reviews",
          %{
            repo: "org/repo",
            pr_number: 42,
            head_sha: "abc123def456"
          },
          store
        )

      assert conn.status == 202
      body = Jason.decode!(conn.resp_body)
      assert is_integer(body["review_id"])
      assert body["status"] == "queued"
    end

    test "uses request github_token for every GitHub API call during the review run", ctx do
      test_pid = self()

      with_env("GH_TOKEN", "server-env-token", fn ->
        pipeline_fn =
          async_pipeline_fn(test_pid, ctx,
            github_req_builder: fn token, _github_opts ->
              send(test_pid, {:github_req_builder_token, token})

              mock_github_req(%{}, test_pid)
              |> Req.merge(headers: [{"authorization", "Bearer #{token}"}])
            end
          )

        conn =
          json_post(
            "/api/reviews",
            %{
              repo: "org/repo",
              pr_number: 42,
              head_sha: "abc123def456",
              github_token: "request-scope-token"
            },
            ctx.store,
            pipeline: pipeline_fn
          )

        assert conn.status == 202
        %{"review_id" => review_id} = Jason.decode!(conn.resp_body)

        assert_receive {:github_req_builder_token, "request-scope-token"}, 1_000
        assert_receive {:pipeline_finished, ^review_id, {:ok, _aggregated}}, 5_000

        auth_headers = collect_github_auth_headers()
        assert auth_headers != []
        assert Enum.uniq(auth_headers) == ["Bearer request-scope-token"]
      end)
    end

    test "passes nil github_token to the injected builder when request github_token is omitted",
         ctx do
      test_pid = self()

      pipeline_fn =
        async_pipeline_fn(test_pid, ctx,
          github_req_builder: fn token, _github_opts ->
            send(test_pid, {:github_req_builder_token, token})

            mock_github_req(%{}, test_pid)
            |> Req.merge(headers: [{"authorization", "Bearer test-token"}])
          end
        )

      conn =
        json_post(
          "/api/reviews",
          %{
            repo: "org/repo",
            pr_number: 42,
            head_sha: "abc123def456"
          },
          ctx.store,
          pipeline: pipeline_fn
        )

      assert conn.status == 202
      %{"review_id" => review_id} = Jason.decode!(conn.resp_body)

      assert_receive {:github_req_builder_token, nil}, 1_000
      assert_receive {:pipeline_finished, ^review_id, {:ok, _aggregated}}, 5_000
    end

    test "treats whitespace-only github_token as omitted before calling the injected builder", ctx do
      test_pid = self()

      pipeline_fn =
        async_pipeline_fn(test_pid, ctx,
          github_req_builder: fn token, _github_opts ->
            send(test_pid, {:github_req_builder_token, token})

            mock_github_req(%{}, test_pid)
            |> Req.merge(headers: [{"authorization", "Bearer test-token"}])
          end
        )

      conn =
        json_post(
          "/api/reviews",
          %{
            repo: "org/repo",
            pr_number: 42,
            head_sha: "abc123def456",
            github_token: " \t "
          },
          ctx.store,
          pipeline: pipeline_fn
        )

      assert conn.status == 202
      %{"review_id" => review_id} = Jason.decode!(conn.resp_body)

      assert_receive {:github_req_builder_token, nil}, 1_000
      assert_receive {:pipeline_finished, ^review_id, {:ok, _aggregated}}, 5_000
    end

    test "rejects github_token values that would break request headers", %{store: store} do
      conn =
        json_post(
          "/api/reviews",
          %{
            repo: "org/repo",
            pr_number: 42,
            head_sha: "abc123def456",
            github_token: "good\r\nbad"
          },
          store
        )

      assert conn.status == 422
      body = Jason.decode!(conn.resp_body)
      assert body["error"] == "invalid field: github_token"
    end

    test "fails clearly when the request github_token is invalid", ctx do
      test_pid = self()

      with_env("GH_TOKEN", "server-env-token", fn ->
        pipeline_fn =
          async_pipeline_fn(test_pid, ctx,
            github_req_builder: fn token, _github_opts ->
              send(test_pid, {:github_req_builder_token, token})

              mock_github_req(
                %{
                  pr_context: %Req.Response{
                    status: 401,
                    body: %{"message" => "Bad credentials"}
                  }
                },
                test_pid
              )
              |> Req.merge(headers: [{"authorization", "Bearer #{token}"}])
            end
          )

        conn =
          json_post(
            "/api/reviews",
            %{
              repo: "org/repo",
              pr_number: 42,
              head_sha: "abc123def456",
              github_token: "bad-request-token"
            },
            ctx.store,
            pipeline: pipeline_fn
          )

        assert conn.status == 202
        %{"review_id" => review_id} = Jason.decode!(conn.resp_body)

        assert_receive {:github_req_builder_token, "bad-request-token"}, 1_000

        assert_receive {:pipeline_finished, ^review_id, {:error, {:pipeline_failed, message}}},
                       5_000

        assert message =~ "Authentication failed (401)"

        failed_body = wait_for_status(ctx.store, review_id, "failed")
        assert failed_body["status"] == "failed"

        assert {:ok, [%{kind: "pipeline_error", payload: payload}]} =
                 Cerberus.Store.list_events(ctx.store, review_id)

        assert payload["error"] =~ "Authentication failed (401)"
      end)
    end
  end

  # --- GET /api/reviews/:id ---

  describe "GET /api/reviews/:id" do
    test "returns 404 for non-existent review", %{store: store} do
      conn = authed_get("/api/reviews/99999", store)
      assert conn.status == 404
      body = Jason.decode!(conn.resp_body)
      assert body["error"] == "not_found"
    end

    test "returns 404 for non-integer id", %{store: store} do
      conn = authed_get("/api/reviews/abc", store)
      assert conn.status == 404
    end

    test "returns queued review status after creation", %{store: store} do
      post_conn =
        json_post(
          "/api/reviews",
          %{
            repo: "org/repo",
            pr_number: 42,
            head_sha: "abc123def456"
          },
          store
        )

      assert post_conn.status == 202
      %{"review_id" => id} = Jason.decode!(post_conn.resp_body)

      conn = authed_get("/api/reviews/#{id}", store)
      assert conn.status == 200
      body = Jason.decode!(conn.resp_body)
      assert body["review_id"] == id
      assert body["status"] == "queued"
      assert body["repo"] == "org/repo"
      assert body["pr_number"] == 42
    end

    test "ignores unrecognized fields in request", %{store: store} do
      post_conn =
        json_post(
          "/api/reviews",
          %{
            repo: "org/repo",
            pr_number: 42,
            head_sha: "abc123",
            extra_field: "should-be-ignored"
          },
          store
        )

      %{"review_id" => id} = Jason.decode!(post_conn.resp_body)

      conn = authed_get("/api/reviews/#{id}", store)
      body = Jason.decode!(conn.resp_body)
      refute Map.has_key?(body, "extra_field")
    end

    test "returns running during async execution and completed after release", ctx do
      test_pid = self()
      blocker = make_ref()

      call_llm = fn _params ->
        send(test_pid, {:reviewer_blocked, self(), blocker})

        receive do
          {:release_reviewer, ^blocker} ->
            {:ok,
             %{
               content: @valid_verdict_json,
               tool_calls: nil,
               usage: %{prompt_tokens: 100, completion_tokens: 50}
             }}
        after
          5_000 -> {:error, :timeout}
        end
      end

      pipeline_fn = fn review_id, params ->
        spawn(fn ->
          send(test_pid, {:pipeline_started, review_id})
          result = Pipeline.run(review_id, params, pipeline_opts(ctx, call_llm: call_llm))
          send(test_pid, {:pipeline_finished, review_id, result})
        end)
      end

      post_conn =
        json_post(
          "/api/reviews",
          %{repo: "org/repo", pr_number: 42, head_sha: "abc123def456"},
          ctx.store,
          pipeline: pipeline_fn
        )

      assert post_conn.status == 202
      %{"review_id" => id, "status" => "queued"} = Jason.decode!(post_conn.resp_body)

      assert_receive {:pipeline_started, ^id}, 1_000
      assert_receive {:reviewer_blocked, reviewer_pid, ^blocker}, 1_000

      running_body = wait_for_status(ctx.store, id, "running")
      assert running_body["review_id"] == id
      assert running_body["status"] == "running"

      send(reviewer_pid, {:release_reviewer, blocker})

      assert_receive {:pipeline_finished, ^id, {:ok, _aggregated}}, 5_000

      completed_body = wait_for_status(ctx.store, id, "completed")
      assert completed_body["review_id"] == id
      assert completed_body["status"] == "completed"
      assert is_map(completed_body["aggregated_verdict"])
    end
  end

  # --- Error handling ---

  describe "POST /api/reviews error handling" do
    test "returns 500 when store fails", %{store: _store} do
      # Use a fake store pid that will crash
      {:ok, dead_store} = Agent.start_link(fn -> nil end)
      Agent.stop(dead_store)

      conn =
        conn(
          :post,
          "/api/reviews",
          Jason.encode!(%{repo: "org/repo", pr_number: 42, head_sha: "abc"})
        )
        |> put_req_header("content-type", "application/json")
        |> put_req_header("authorization", "Bearer #{@api_key}")
        |> API.call(API.init(api_key: @api_key, store: dead_store))

      # GenServer call to dead process will raise
      assert conn.status == 500
    end
  end

  # --- 404 ---

  describe "unknown routes" do
    test "returns 404", %{store: store} do
      conn = authed_get("/api/nonexistent", store)
      assert conn.status == 404
    end
  end
end
