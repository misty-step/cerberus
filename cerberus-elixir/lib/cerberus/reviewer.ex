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
  @openrouter_url "https://openrouter.ai/api/v1/chat/completions"

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
    timeout = timeout || GenServer.call(server, :timeout_ms)
    GenServer.call(server, {:review, pr_context}, timeout)
  end

  # --- Server Callbacks ---

  @impl true
  def init(opts) do
    {:ok,
     %{
       perspective: Keyword.fetch!(opts, :perspective),
       model: Keyword.fetch!(opts, :model),
       config_server: Keyword.get(opts, :config_server, Cerberus.Config),
       call_llm: Keyword.get(opts, :call_llm, &default_call_llm/1),
       tool_handler: Keyword.get(opts, :tool_handler, &noop_tool_handler/1),
       max_retries: Keyword.get(opts, :max_retries, @default_max_retries),
       fallback_models: Keyword.get(opts, :fallback_models, []),
       timeout_ms: Keyword.get(opts, :timeout_ms, @default_timeout_ms),
       max_steps: Keyword.get(opts, :max_steps, @default_max_steps),
       repo_root: Keyword.get(opts, :repo_root)
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
      Logger.warning("Reviewer #{state.perspective} crashed: #{Exception.message(e)}")
      {:reply, {:error, {:crash, Exception.message(e)}}, state}
  end

  # --- Review Execution ---

  defp execute_review(pr_context, state) do
    perspective = to_string(state.perspective)

    case find_persona(perspective, state.config_server) do
      nil ->
        {:error, {:unknown_perspective, perspective}}

      persona ->
        {system_prompt, user_prompt} = build_prompts(persona, pr_context, state)
        tools = Cerberus.Tools.GithubRead.definitions()

        messages = [
          %{"role" => "system", "content" => system_prompt},
          %{"role" => "user", "content" => user_prompt}
        ]

        models = Enum.uniq([state.model | state.fallback_models])
        try_with_fallback(models, messages, tools, state)
    end
  end

  defp find_persona(perspective, config_server) do
    config_server
    |> Cerberus.Config.personas()
    |> Enum.find(&(to_string(&1.perspective) == perspective))
  end

  defp build_prompts(persona, pr_context, state) do
    system_prompt = persona.prompt
    repo_root = state.repo_root || Cerberus.repo_root()

    template =
      case Cerberus.ReviewPrompt.load_template(repo_root) do
        {:ok, t} -> t
        {:error, _} -> "Review the PR diff at {{DIFF_FILE}} from the {{PERSPECTIVE}} perspective."
      end

    vars =
      pr_context
      |> Map.put(:perspective, to_string(state.perspective))
      |> Cerberus.ReviewPrompt.build_vars()

    user_prompt = Cerberus.ReviewPrompt.render(template, vars)
    {system_prompt, user_prompt}
  end

  # --- Retry + Fallback ---

  defp try_with_fallback([], _messages, _tools, _state) do
    {:error, :all_models_exhausted}
  end

  defp try_with_fallback([model | rest], messages, tools, state) do
    case try_model(model, messages, tools, state, 0) do
      {:ok, _} = success -> success
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

  defp run_conversation(_model, _messages, _tools, state, step, _usage)
       when step >= state.max_steps do
    {:error, :max_steps_exceeded}
  end

  defp run_conversation(model, messages, tools, state, step, usage) do
    params = %{model: model, messages: messages, tools: tools, max_tokens: 16_000}

    case state.call_llm.(params) do
      {:ok, %{tool_calls: tcs} = resp} when is_list(tcs) and tcs != [] ->
        accumulated = accumulate_usage(usage, resp[:usage])
        new_msgs = execute_tools(tcs, state.tool_handler)
        assistant_msg = build_assistant_tool_msg(tcs)

        run_conversation(
          model,
          messages ++ [assistant_msg | new_msgs],
          tools,
          state,
          step + 1,
          accumulated
        )

      {:ok, %{content: content} = resp} when is_binary(content) ->
        accumulated = accumulate_usage(usage, resp[:usage])

        case Cerberus.Verdict.parse(content) do
          {:ok, verdict} -> {:ok, %{verdict: verdict, usage: accumulated}}
          {:error, reason} -> {:error, {:invalid_verdict, reason}}
        end

      {:ok, _} ->
        {:error, :empty_response}

      {:error, :transient} ->
        {:error, :transient}

      {:error, reason} ->
        {:error, {:permanent, reason}}
    end
  end

  defp execute_tools(tool_calls, tool_handler) do
    results =
      Enum.map(tool_calls, fn tc ->
        args =
          case Jason.decode(tc.function.arguments) do
            {:ok, parsed} -> parsed
            {:error, _} -> %{}
          end

        result = tool_handler.(%{name: tc.function.name, arguments: args})

        %{
          "role" => "tool",
          "tool_call_id" => tc.id,
          "content" => format_tool_result(result)
        }
      end)

    results
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

  defp format_tool_result({:ok, result}), do: to_string(result)
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

  defp emit_telemetry({:ok, %{usage: usage}}, elapsed_ms, state) do
    :telemetry.execute(
      [:cerberus, :reviewer, :complete],
      %{
        duration_ms: elapsed_ms,
        prompt_tokens: usage.prompt_tokens,
        completion_tokens: usage.completion_tokens
      },
      %{perspective: state.perspective, model: state.model}
    )
  end

  defp emit_telemetry({:error, _}, elapsed_ms, state) do
    :telemetry.execute(
      [:cerberus, :reviewer, :error],
      %{duration_ms: elapsed_ms},
      %{perspective: state.perspective, model: state.model}
    )
  end

  # --- Default LLM Transport ---

  defp default_call_llm(params) do
    api_key =
      System.get_env("CERBERUS_API_KEY") ||
        System.get_env("CERBERUS_OPENROUTER_API_KEY") ||
        System.get_env("OPENROUTER_API_KEY")

    if is_nil(api_key) or api_key == "" do
      {:error, :no_api_key}
    else
      do_call_openrouter(api_key, params)
    end
  end

  defp do_call_openrouter(api_key, params) do
    payload =
      %{
        model: params.model,
        messages: params.messages,
        max_tokens: params.max_tokens
      }
      |> maybe_add_tools(params.tools)

    case Req.post(@openrouter_url,
           json: payload,
           headers: [
             {"authorization", "Bearer #{api_key}"},
             {"user-agent", "cerberus-reviewer/1.0"},
             {"http-referer", "https://github.com/misty-step/cerberus"},
             {"x-title", "Cerberus Reviewer"}
           ],
           receive_timeout: 120_000
         ) do
      {:ok, %{status: 200, body: body}} ->
        parse_openrouter_response(body)

      {:ok, %{status: status}} when status in [429, 500, 502, 503] ->
        {:error, :transient}

      {:ok, %{status: status, body: body}} ->
        {:error, {:http_error, status, inspect(body)}}

      {:error, %{reason: :timeout}} ->
        {:error, :transient}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp maybe_add_tools(payload, tools) when is_list(tools) and tools != [] do
    Map.put(payload, :tools, tools)
  end

  defp maybe_add_tools(payload, _), do: payload

  defp parse_openrouter_response(body) when is_map(body) do
    with choices when is_list(choices) and choices != [] <- body["choices"],
         message when is_map(message) <- hd(choices)["message"] do
      {:ok,
       %{
         content: message["content"],
         tool_calls: parse_tool_calls(message["tool_calls"]),
         usage: parse_usage(body["usage"])
       }}
    else
      _ -> {:error, :invalid_response}
    end
  end

  defp parse_openrouter_response(_), do: {:error, :invalid_response}

  defp parse_tool_calls(nil), do: []

  defp parse_tool_calls(tcs) when is_list(tcs) do
    Enum.map(tcs, fn tc ->
      %{
        id: tc["id"],
        function: %{
          name: get_in(tc, ["function", "name"]),
          arguments: get_in(tc, ["function", "arguments"]) || "{}"
        }
      }
    end)
  end

  defp parse_usage(nil), do: %{prompt_tokens: 0, completion_tokens: 0}

  defp parse_usage(u) when is_map(u) do
    %{
      prompt_tokens: u["prompt_tokens"] || 0,
      completion_tokens: u["completion_tokens"] || 0
    }
  end

  defp noop_tool_handler(%{name: name}) do
    {:error, "Tool #{name} not available in this context"}
  end
end
