defmodule Cerberus.ReviewerTest do
  use ExUnit.Case, async: true

  alias Cerberus.Reviewer

  @repo_root Path.expand("../../..", __DIR__)

  defp valid_verdict_json do
    Jason.encode!(%{
      "reviewer" => "trace",
      "perspective" => "correctness",
      "verdict" => "PASS",
      "confidence" => 0.85,
      "summary" => "No significant issues found.",
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

  defp pr_context do
    %{
      title: "Fix null check in parser",
      author: "dev",
      head_branch: "fix/null-check",
      base_branch: "main",
      body: "Fixes null pointer in parse step.",
      diff_file: "/tmp/pr.diff"
    }
  end

  defp setup_config(ctx \\ %{}) do
    config_name = :"config_reviewer_#{System.unique_integer([:positive])}"
    {:ok, _} = Cerberus.Config.start_link(repo_root: @repo_root, name: config_name)
    Map.put(ctx, :config, config_name)
  end

  # Mock that returns a sequence of responses
  defp sequence_mock(responses) do
    {:ok, agent} = Agent.start_link(fn -> responses end)

    mock = fn _params ->
      Agent.get_and_update(agent, fn
        [resp | rest] -> {resp, rest}
        [] -> {{:error, :exhausted}, []}
      end)
    end

    {mock, agent}
  end

  # Simple mock that always returns a verdict
  defp success_mock do
    fn _params ->
      {:ok,
       %{
         content: valid_verdict_json(),
         tool_calls: [],
         usage: %{prompt_tokens: 500, completion_tokens: 200}
       }}
    end
  end

  # --- GenServer lifecycle ---

  describe "start_link/1" do
    test "starts under DynamicSupervisor with perspective and model" do
      %{config: config} = setup_config()

      {:ok, sup} = DynamicSupervisor.start_link(strategy: :one_for_one)

      {:ok, pid} =
        DynamicSupervisor.start_child(sup, {
          Reviewer,
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: success_mock(),
          repo_root: @repo_root
        })

      assert Process.alive?(pid)
      DynamicSupervisor.terminate_child(sup, pid)
    end

    test "requires perspective and model" do
      Process.flag(:trap_exit, true)

      assert {:error, {%KeyError{key: :perspective}, _}} =
               Reviewer.start_link(model: "test")

      assert {:error, {%KeyError{key: :model}, _}} =
               Reviewer.start_link(perspective: :correctness)
    end
  end

  # --- System prompt ---

  describe "system prompt loading" do
    test "sends persona system prompt as first message" do
      %{config: config} = setup_config()
      test_pid = self()

      capturing_llm = fn params ->
        send(test_pid, {:llm_params, params})

        {:ok,
         %{
           content: valid_verdict_json(),
           tool_calls: [],
           usage: %{prompt_tokens: 100, completion_tokens: 50}
         }}
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: capturing_llm,
          repo_root: @repo_root
        )

      {:ok, _} = Reviewer.review(pid, pr_context())

      assert_receive {:llm_params, params}
      [system_msg | _] = params.messages
      assert system_msg["role"] == "system"
      # System prompt comes from pi/agents/correctness.md
      assert byte_size(system_msg["content"]) > 0
    end
  end

  # --- User prompt rendering ---

  describe "user prompt rendering" do
    test "renders template with PR context variables" do
      %{config: config} = setup_config()
      test_pid = self()

      capturing_llm = fn params ->
        send(test_pid, {:llm_params, params})

        {:ok,
         %{
           content: valid_verdict_json(),
           tool_calls: [],
           usage: %{prompt_tokens: 100, completion_tokens: 50}
         }}
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: capturing_llm,
          repo_root: @repo_root
        )

      {:ok, _} = Reviewer.review(pid, pr_context())

      assert_receive {:llm_params, params}
      [_, user_msg | _] = params.messages
      assert user_msg["role"] == "user"
      content = user_msg["content"]
      # Template placeholders should be filled
      assert content =~ "Fix null check in parser"
      assert content =~ "fix/null-check"
      assert content =~ "correctness"
      refute content =~ "{{PR_TITLE}}"
    end
  end

  # --- Tool definitions ---

  describe "tool definitions" do
    test "LLM request includes tool definitions" do
      %{config: config} = setup_config()
      test_pid = self()

      capturing_llm = fn params ->
        send(test_pid, {:llm_params, params})

        {:ok,
         %{
           content: valid_verdict_json(),
           tool_calls: [],
           usage: %{prompt_tokens: 100, completion_tokens: 50}
         }}
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: capturing_llm,
          repo_root: @repo_root
        )

      {:ok, _} = Reviewer.review(pid, pr_context())

      assert_receive {:llm_params, params}
      assert is_list(params.tools)
      assert length(params.tools) == 3
      names = Enum.map(params.tools, &get_in(&1, ["function", "name"]))
      assert "get_file_contents" in names
      assert "search_code" in names
      assert "list_directory" in names
    end
  end

  # --- Tool calling loop ---

  describe "tool calling" do
    test "executes tool calls and continues conversation" do
      %{config: config} = setup_config()
      test_pid = self()

      tool_call = %{
        id: "call_1",
        function: %{name: "get_file_contents", arguments: ~s({"path": "lib/foo.ex"})}
      }

      {mock, _} =
        sequence_mock([
          # First response: tool call
          {:ok,
           %{
             content: nil,
             tool_calls: [tool_call],
             usage: %{prompt_tokens: 100, completion_tokens: 20}
           }},
          # Second response: verdict
          {:ok,
           %{
             content: valid_verdict_json(),
             tool_calls: [],
             usage: %{prompt_tokens: 200, completion_tokens: 100}
           }}
        ])

      tool_handler = fn %{name: name, arguments: args} ->
        send(test_pid, {:tool_called, name, args})
        {:ok, "defmodule Foo do\n  def hello, do: :world\nend"}
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: mock,
          tool_handler: tool_handler,
          repo_root: @repo_root
        )

      assert {:ok, %{verdict: verdict}} = Reviewer.review(pid, pr_context())
      assert verdict.verdict == "PASS"

      assert_receive {:tool_called, "get_file_contents", %{"path" => "lib/foo.ex"}}
    end

    test "handles tool errors gracefully" do
      %{config: config} = setup_config()

      tool_call = %{
        id: "call_1",
        function: %{name: "get_file_contents", arguments: ~s({"path": "nonexistent.ex"})}
      }

      {mock, _} =
        sequence_mock([
          {:ok,
           %{
             content: nil,
             tool_calls: [tool_call],
             usage: %{prompt_tokens: 100, completion_tokens: 20}
           }},
          {:ok,
           %{
             content: valid_verdict_json(),
             tool_calls: [],
             usage: %{prompt_tokens: 200, completion_tokens: 100}
           }}
        ])

      error_handler = fn _call -> {:error, "File not found"} end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: mock,
          tool_handler: error_handler,
          repo_root: @repo_root
        )

      # Should still complete — tool errors become error messages in the conversation
      assert {:ok, _} = Reviewer.review(pid, pr_context())
    end
  end

  # --- Verdict validation ---

  describe "verdict validation" do
    test "returns validated verdict struct on success" do
      %{config: config} = setup_config()

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: success_mock(),
          repo_root: @repo_root
        )

      assert {:ok, %{verdict: verdict}} = Reviewer.review(pid, pr_context())
      assert %Cerberus.Verdict{} = verdict
      assert verdict.verdict == "PASS"
      assert verdict.confidence == 0.85
      assert verdict.reviewer == "trace"
    end

    test "rejects invalid verdict JSON" do
      %{config: config} = setup_config()

      bad_llm = fn _params ->
        {:ok,
         %{
           content: "not valid json {{{",
           tool_calls: [],
           usage: %{prompt_tokens: 50, completion_tokens: 10}
         }}
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: bad_llm,
          repo_root: @repo_root
        )

      assert {:error, _} = Reviewer.review(pid, pr_context())
    end
  end

  # --- Retry with model fallback ---

  describe "retry and fallback" do
    test "retries up to 3 times on transient errors" do
      %{config: config} = setup_config()

      {mock, _} =
        sequence_mock([
          {:error, :transient},
          {:error, :transient},
          {:ok,
           %{
             content: valid_verdict_json(),
             tool_calls: [],
             usage: %{prompt_tokens: 100, completion_tokens: 50}
           }}
        ])

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: mock,
          repo_root: @repo_root
        )

      assert {:ok, %{verdict: verdict}} = Reviewer.review(pid, pr_context())
      assert verdict.verdict == "PASS"
    end

    test "advances to fallback model after max retries" do
      %{config: config} = setup_config()
      test_pid = self()

      call_count = :counters.new(1, [])

      fallback_llm = fn params ->
        :counters.add(call_count, 1, 1)
        n = :counters.get(call_count, 1)
        send(test_pid, {:call, n, params.model})

        if params.model == "primary-model" do
          {:error, :transient}
        else
          {:ok,
           %{
             content: valid_verdict_json(),
             tool_calls: [],
             usage: %{prompt_tokens: 100, completion_tokens: 50}
           }}
        end
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "primary-model",
          fallback_models: ["fallback-model"],
          config_server: config,
          call_llm: fallback_llm,
          repo_root: @repo_root
        )

      assert {:ok, %{verdict: verdict}} = Reviewer.review(pid, pr_context())
      assert verdict.verdict == "PASS"

      # Primary tried 3 times, then fallback succeeded
      assert_receive {:call, _, "fallback-model"}
    end

    test "returns error when all models exhausted" do
      %{config: config} = setup_config()

      always_fail = fn _params -> {:error, :transient} end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "only-model",
          config_server: config,
          call_llm: always_fail,
          repo_root: @repo_root
        )

      assert {:error, :all_models_exhausted} = Reviewer.review(pid, pr_context())
    end

    test "short-circuits on permanent errors without trying fallback" do
      %{config: config} = setup_config()
      test_pid = self()

      perm_fail = fn params ->
        send(test_pid, {:called, params.model})
        {:error, {:permanent, :no_api_key}}
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "primary",
          fallback_models: ["fallback"],
          config_server: config,
          call_llm: perm_fail,
          repo_root: @repo_root
        )

      assert {:error, {:permanent, :no_api_key}} = Reviewer.review(pid, pr_context())

      # Only primary was called, fallback was never tried
      assert_receive {:called, "primary"}
      refute_receive {:called, "fallback"}
    end
  end

  # --- Timeout ---

  describe "timeout" do
    test "defaults to 600_000ms" do
      %{config: config} = setup_config()

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: success_mock(),
          repo_root: @repo_root
        )

      assert GenServer.call(pid, :timeout_ms) == 600_000
    end

    test "is configurable per perspective" do
      %{config: config} = setup_config()

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: success_mock(),
          timeout_ms: 300_000,
          repo_root: @repo_root
        )

      assert GenServer.call(pid, :timeout_ms) == 300_000
    end
  end

  # --- Telemetry ---

  describe "telemetry" do
    test "emits completion event with token usage" do
      %{config: config} = setup_config()
      test_pid = self()

      :telemetry.attach(
        "test-reviewer-complete",
        [:cerberus, :reviewer, :complete],
        fn event, measurements, metadata, _ ->
          send(test_pid, {:telemetry, event, measurements, metadata})
        end,
        nil
      )

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: success_mock(),
          repo_root: @repo_root
        )

      {:ok, _} = Reviewer.review(pid, pr_context())

      assert_receive {:telemetry, [:cerberus, :reviewer, :complete], measurements,
                      %{perspective: :correctness, model: "test-model"} = metadata}
      assert measurements.prompt_tokens == 500
      assert measurements.completion_tokens == 200
      assert measurements.duration_ms >= 0
      assert metadata.perspective == :correctness

      :telemetry.detach("test-reviewer-complete")
    end

    test "emits error event on failure" do
      %{config: config} = setup_config()
      test_pid = self()

      :telemetry.attach(
        "test-reviewer-error",
        [:cerberus, :reviewer, :error],
        fn event, measurements, metadata, _ ->
          send(test_pid, {:telemetry, event, measurements, metadata})
        end,
        nil
      )

      always_fail = fn _params -> {:error, :transient} end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: always_fail,
          repo_root: @repo_root
        )

      {:error, _} = Reviewer.review(pid, pr_context())

      assert_receive {:telemetry, [:cerberus, :reviewer, :error], measurements,
                      %{perspective: :correctness, model: "test-model"}}
      assert measurements.duration_ms >= 0

      :telemetry.detach("test-reviewer-error")
    end

    test "emits actual model used on fallback, not primary" do
      %{config: config} = setup_config()
      test_pid = self()

      :telemetry.attach(
        "test-reviewer-fallback-model",
        [:cerberus, :reviewer, :complete],
        fn event, measurements, metadata, _ ->
          send(test_pid, {:telemetry, event, measurements, metadata})
        end,
        nil
      )

      fallback_llm = fn params ->
        if params.model == "primary-model" do
          {:error, :transient}
        else
          {:ok,
           %{
             content: valid_verdict_json(),
             tool_calls: [],
             usage: %{prompt_tokens: 100, completion_tokens: 50}
           }}
        end
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "primary-model",
          fallback_models: ["fallback-model"],
          config_server: config,
          call_llm: fallback_llm,
          repo_root: @repo_root
        )

      {:ok, _} = Reviewer.review(pid, pr_context())

      assert_receive {:telemetry, [:cerberus, :reviewer, :complete], _measurements,
                      %{perspective: :correctness, model: "fallback-model"}}

      :telemetry.detach("test-reviewer-fallback-model")
    end
  end

  # --- Token usage accumulation ---

  describe "usage accumulation" do
    test "accumulates tokens across multi-turn conversation" do
      %{config: config} = setup_config()

      tool_call = %{
        id: "call_1",
        function: %{name: "get_file_contents", arguments: ~s({"path": "lib/foo.ex"})}
      }

      {mock, _} =
        sequence_mock([
          {:ok,
           %{
             content: nil,
             tool_calls: [tool_call],
             usage: %{prompt_tokens: 100, completion_tokens: 20}
           }},
          {:ok,
           %{
             content: valid_verdict_json(),
             tool_calls: [],
             usage: %{prompt_tokens: 300, completion_tokens: 150}
           }}
        ])

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: mock,
          tool_handler: fn _ -> {:ok, "file contents"} end,
          repo_root: @repo_root
        )

      assert {:ok, %{usage: usage}} = Reviewer.review(pid, pr_context())
      assert usage.prompt_tokens == 400
      assert usage.completion_tokens == 170
    end
  end

  # --- Max steps ---

  describe "max_steps guard" do
    test "stops conversation after max steps" do
      %{config: config} = setup_config()

      # LLM that always returns tool calls, never a verdict
      infinite_tools = fn _params ->
        {:ok,
         %{
           content: nil,
           tool_calls: [
             %{
               id: "call_#{System.unique_integer()}",
               function: %{name: "list_directory", arguments: ~s({"path": "."})}
             }
           ],
           usage: %{prompt_tokens: 10, completion_tokens: 5}
         }}
      end

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :correctness,
          model: "test-model",
          config_server: config,
          call_llm: infinite_tools,
          tool_handler: fn _ -> {:ok, "dir listing"} end,
          max_steps: 3,
          repo_root: @repo_root
        )

      assert {:error, :all_models_exhausted} = Reviewer.review(pid, pr_context())
    end
  end

  # --- Unknown perspective ---

  describe "unknown perspective" do
    test "returns error for non-existent perspective" do
      %{config: config} = setup_config()

      {:ok, pid} =
        Reviewer.start_link(
          perspective: :nonexistent,
          model: "test-model",
          config_server: config,
          call_llm: success_mock(),
          repo_root: @repo_root
        )

      assert {:error, {:unknown_perspective, "nonexistent"}} = Reviewer.review(pid, pr_context())
    end
  end
end
