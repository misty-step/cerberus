defmodule Cerberus.EngineTest do
  use ExUnit.Case, async: false

  alias Cerberus.Engine
  import ExUnit.CaptureLog

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

  defmodule StoreSpy do
    use GenServer

    def start_link(test_pid) do
      GenServer.start_link(__MODULE__, test_pid)
    end

    @impl true
    def init(test_pid), do: {:ok, test_pid}

    @impl true
    def handle_call(message, _from, test_pid) do
      send(test_pid, {:unexpected_store_call, message})
      {:reply, :ok, test_pid}
    end
  end

  setup do
    Process.flag(:trap_exit, true)
    uid = System.unique_integer([:positive])

    repo_root = Application.fetch_env!(:cerberus_elixir, :repo_root)
    config_name = :"engine_test_config_#{uid}"
    {:ok, _config} = Cerberus.Config.start_link(name: config_name, repo_root: repo_root)

    router_llm = fn _params ->
      {:ok, ["correctness", "security", "architecture", "testing"]}
    end

    router_name = :"engine_test_router_#{uid}"

    {:ok, router} =
      Cerberus.Router.start_link(
        name: router_name,
        config_server: config_name,
        call_llm: router_llm
      )

    {:ok, supervisor} = DynamicSupervisor.start_link(strategy: :one_for_one)
    {:ok, task_sup} = Task.Supervisor.start_link()

    %{
      config: config_name,
      router: router,
      supervisor: supervisor,
      task_sup: task_sup,
      repo_root: repo_root
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

  defp context(overrides \\ %{}) do
    Map.merge(
      %{
        title: "Test PR",
        author: "testuser",
        head_ref: "feat/test",
        base_ref: "main",
        body: "Test PR body"
      },
      overrides
    )
  end

  defp engine_opts(ctx, overrides \\ []) do
    [
      config_server: ctx.config,
      router_server: ctx.router,
      supervisor: ctx.supervisor,
      task_supervisor: ctx.task_sup,
      call_llm: Keyword.get(overrides, :call_llm, &mock_llm_pass/1),
      repo_root: ctx.repo_root,
      reviewer_timeout: Keyword.get(overrides, :reviewer_timeout, 30_000)
    ] ++ Keyword.drop(overrides, [:call_llm, :reviewer_timeout])
  end

  describe "review/3" do
    test "returns aggregated review data for diff and context", ctx do
      assert {:ok, result} = Engine.review(@diff, context(), engine_opts(ctx))

      assert result.verdict in ["PASS", "WARN", "SKIP"]
      assert is_binary(result.summary)
      assert is_map(result.stats)
      assert is_map(result.cost)
      assert result.stats.total == 4
      assert length(result.reviewers) == 4
      assert length(result.reviewer_results) == 4
      assert Enum.sort(Map.keys(result.cost.per_reviewer)) == ["atlas", "guard", "proof", "trace"]
    end

    test "does not call Store even if a store-like dependency is passed", ctx do
      {:ok, store_spy} = StoreSpy.start_link(self())

      assert {:ok, _result} =
               Engine.review(@diff, context(), engine_opts(ctx, store: store_spy))

      refute_receive {:unexpected_store_call, _}
    end

    test "does not use github_opts when no GitHub-backed tool handler is injected", ctx do
      test_pid = self()

      github_req =
        Req.new(
          adapter: fn request ->
            send(test_pid, {:unexpected_github_request, request.method, request.url})
            {request, %Req.Response{status: 200, body: %{}}}
          end
        )

      assert {:ok, _result} =
               Engine.review(
                 @diff,
                 context(),
                 engine_opts(ctx, github_opts: [req: github_req, max_retries: 0])
               )

      refute_receive {:unexpected_github_request, _, _}
    end

    test "logs reviewer failures before degrading them to skip", ctx do
      log =
        capture_log(fn ->
          assert {:ok, result} =
                   Engine.review(
                     @diff,
                     context(),
                     engine_opts(ctx, call_llm: fn _params -> {:error, :boom} end)
                   )

          assert result.verdict == "SKIP"
          assert Enum.all?(result.reviewer_results, &(&1.status == :error))
        end)

      assert log =~ "Reviewer correctness failed: {:permanent, :boom}"
    end
  end
end
