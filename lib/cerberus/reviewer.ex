defmodule Cerberus.Reviewer do
  @moduledoc """
  GenServer that executes a single-perspective code review.

  Started under `Cerberus.ReviewSupervisor` (DynamicSupervisor) with a
  perspective assignment and model. Manages the multi-turn LLM conversation
  (tool calls → tool results → verdict), validates the response, and retries
  on transient failures with model fallback.

  ## Usage

      {:ok, pid} = DynamicSupervisor.start_child(
        Cerberus.ReviewSupervisor,
        {Cerberus.Reviewer, perspective: :correctness, model: "openrouter/..."}
      )
      {:ok, result} = Cerberus.Reviewer.review(pid, pr_context)
  """

  use GenServer
  require Logger

  @default_timeout_ms 600_000
  @default_max_retries 3
  @default_max_steps 25

  # --- Client API ---

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts)
  end

  @doc """
  Execute a review for the given PR context.

  Returns `{:ok, %{verdict: %Cerberus.Verdict{}, usage: %{...}}}` on success,
  `{:error, reason}` on failure.
  """
  def review(server, pr_context, timeout \\ nil) do
    GenServer.call(server, {:review, pr_context}, timeout || @default_timeout_ms)
  end

  # --- Server Callbacks ---

  @impl true
  def init(opts) do
    repo_root = Keyword.get(opts, :repo_root)
    reviewer = Keyword.get(opts, :reviewer)

    {:ok,
     %{
       reviewer: reviewer,
       perspective: Keyword.fetch!(opts, :perspective),
       model: Keyword.fetch!(opts, :model),
       model_id: Keyword.get(opts, :model_id),
       provider: Keyword.get(opts, :provider, "openrouter"),
       config_server: Keyword.get(opts, :config_server, Cerberus.Config),
       call_llm: Keyword.get(opts, :call_llm, &Cerberus.LLM.OpenRouter.call/1),
       tool_handler: Keyword.get(opts, :tool_handler, &noop_tool_handler/1),
       max_retries: Keyword.get(opts, :max_retries, @default_max_retries),
       fallback_models: Keyword.get(opts, :fallback_models, []),
       timeout_ms: Keyword.get(opts, :timeout_ms, @default_timeout_ms),
       max_steps: Keyword.get(opts, :max_steps, @default_max_steps),
       repo_root: repo_root,
       template: Keyword.get(opts, :template, load_legacy_template(repo_root))
     }}
  end

  @impl true
  def handle_call(:timeout_ms, _from, state) do
    {:reply, state.timeout_ms, state}
  end

  def handle_call({:review, pr_context}, _from, state) do
    start = System.monotonic_time(:millisecond)
    result = execute_review(pr_context, state)
    elapsed = System.monotonic_time(:millisecond) - start
    emit_telemetry(result, elapsed, state)
    {:reply, result, state}
  rescue
    e ->
      Logger.warning(
        "Reviewer #{state.perspective} crashed: #{Exception.format(:error, e, __STACKTRACE__)}"
      )

      {:reply, {:error, {:crash, Exception.message(e)}}, state}
  end

  # --- Review Execution ---

  defp execute_review(pr_context, state) do
    perspective = to_string(state.perspective)

    case find_persona(state, perspective) do
      nil ->
        {:error, {:unknown_perspective, perspective}}

      persona ->
        {system_prompt, user_prompt} = build_prompts(persona, pr_context, perspective, state)
        tools = Cerberus.Tools.GithubRead.definitions()

        messages = [
          %{"role" => "system", "content" => system_prompt},
          %{"role" => "user", "content" => user_prompt}
        ]

        models = Enum.uniq([state.model | state.fallback_models])
        try_with_fallback(models, messages, tools, state)
    end
  end

  defp find_persona(%{reviewer: reviewer}, _perspective) when not is_nil(reviewer), do: reviewer

  defp find_persona(state, perspective) do
    state.config_server
    |> Cerberus.Config.personas()
    |> Enum.find(&(to_string(&1.perspective) == perspective))
  end

  defp build_prompts(persona, pr_context, perspective, state) do
    vars =
      pr_context
      |> Map.put(:perspective, perspective)
      |> Cerberus.ReviewPrompt.build_vars()

    user_prompt = Cerberus.ReviewPrompt.render(state.template, vars)
    {persona.prompt, user_prompt}
  end

  # --- Retry + Fallback ---

  defp try_with_fallback([], _messages, _tools, _state) do
    {:error, :all_models_exhausted}
  end

  defp try_with_fallback([model | rest], messages, tools, state) do
    case try_model(model, messages, tools, state, 0) do
      {:ok, result} -> {:ok, Map.put(result, :model, model)}
      {:error, {:permanent, _}} = error -> error
      {:error, _} -> try_with_fallback(rest, messages, tools, state)
    end
  end

  defp try_model(_model, _messages, _tools, %{max_retries: max}, attempt)
       when attempt >= max do
    {:error, :max_retries_exceeded}
  end

  defp try_model(model, messages, tools, state, attempt) do
    case run_conversation(model, messages, tools, state, 0, zero_usage()) do
      {:ok, _} = success -> success
      {:error, :transient} -> try_model(model, messages, tools, state, attempt + 1)
      {:error, _} = error -> error
    end
  end

  # --- Conversation Loop ---
  # Messages accumulate in reverse to avoid O(n^2) list append.
  # Reversed to chronological order before each LLM call.

  defp run_conversation(_model, _messages, _tools, state, step, _usage)
       when step >= state.max_steps do
    {:error, :max_steps_exceeded}
  end

  defp run_conversation(model, messages, tools, state, step, usage) do
    params = %{
      provider: state.provider,
      model: model,
      model_id: state.model_id,
      messages: messages,
      tools: tools,
      max_tokens: 16_000
    }

    case state.call_llm.(params) do
      {:ok, %{tool_calls: tcs} = resp} when is_list(tcs) and tcs != [] ->
        accumulated = accumulate_usage(usage, resp[:usage])
        tool_msgs = execute_tools(tcs, state.tool_handler)
        assistant_msg = build_assistant_tool_msg(tcs)

        run_conversation(
          model,
          messages ++ [assistant_msg | tool_msgs],
          tools,
          state,
          step + 1,
          accumulated
        )

      {:ok, %{content: content} = resp} when is_binary(content) ->
        accumulated = accumulate_usage(usage, resp[:usage])

        case Cerberus.Verdict.parse(content) do
          {:ok, verdict} ->
            {:ok,
             %{
               verdict: verdict,
               usage: accumulated,
               provider: state.provider,
               model_id: state.model_id
             }}

          {:error, reason} ->
            {:error, {:invalid_verdict, reason}}
        end

      {:ok, _} ->
        {:error, :empty_response}

      {:error, :transient} ->
        {:error, :transient}

      {:error, {:permanent, _}} = error ->
        error

      {:error, reason} ->
        {:error, {:permanent, reason}}
    end
  end

  defp execute_tools(tool_calls, tool_handler) do
    Enum.map(tool_calls, fn tc ->
      args =
        case Jason.decode(tc.function.arguments) do
          {:ok, parsed} ->
            parsed

          {:error, reason} ->
            Logger.warning(
              "Reviewer: malformed tool arguments for #{tc.function.name}: #{inspect(reason)}"
            )

            %{}
        end

      result = tool_handler.(%{name: tc.function.name, arguments: args})

      %{
        "role" => "tool",
        "tool_call_id" => tc.id,
        "content" => format_tool_result(result)
      }
    end)
  end

  defp build_assistant_tool_msg(tool_calls) do
    %{
      "role" => "assistant",
      "content" => nil,
      "tool_calls" =>
        Enum.map(tool_calls, fn tc ->
          %{
            "id" => tc.id,
            "type" => "function",
            "function" => %{
              "name" => tc.function.name,
              "arguments" => tc.function.arguments
            }
          }
        end)
    }
  end

  defp format_tool_result({:ok, result}) when is_binary(result), do: result
  defp format_tool_result({:ok, result}), do: Jason.encode!(result)
  defp format_tool_result({:error, reason}), do: "Error: #{reason}"

  # --- Usage Tracking ---

  defp zero_usage, do: %{prompt_tokens: 0, completion_tokens: 0}

  defp accumulate_usage(acc, nil), do: acc

  defp accumulate_usage(acc, step) do
    %{
      prompt_tokens: acc.prompt_tokens + (step[:prompt_tokens] || 0),
      completion_tokens: acc.completion_tokens + (step[:completion_tokens] || 0)
    }
  end

  # --- Telemetry ---

  defp emit_telemetry({:ok, %{usage: usage} = result}, elapsed_ms, state) do
    :telemetry.execute(
      [:cerberus, :reviewer, :complete],
      %{
        duration_ms: elapsed_ms,
        prompt_tokens: usage.prompt_tokens,
        completion_tokens: usage.completion_tokens
      },
      %{perspective: state.perspective, model: Map.get(result, :model, state.model)}
    )
  end

  defp emit_telemetry({:error, _}, elapsed_ms, state) do
    :telemetry.execute(
      [:cerberus, :reviewer, :error],
      %{duration_ms: elapsed_ms},
      %{perspective: state.perspective, model: state.model}
    )
  end

  defp noop_tool_handler(%{name: name}) do
    {:error, "Tool #{name} not available in this context"}
  end

  defp load_legacy_template(repo_root) do
    case Cerberus.ReviewPrompt.load_template(repo_root || Cerberus.repo_root()) do
      {:ok, template} ->
        template

      {:error, _reason} ->
        "Review the PR diff at {{DIFF_FILE}} from the {{PERSPECTIVE}} perspective."
    end
  end
end
