defmodule Cerberus.LLM.OpenRouter do
  @moduledoc """
  OpenRouter HTTP transport for LLM calls.

  Handles API key resolution, request formatting, response parsing, and
  transient error classification. Used by both Reviewer and Router via
  the `call_llm` DI seam.

  ## Response shape

      {:ok, %{content: String.t() | nil, tool_calls: [tool_call], usage: usage}}
      {:error, :transient | :no_api_key | {:http_error, status, body}}
  """

  require Logger

  @url "https://openrouter.ai/api/v1/chat/completions"

  @doc """
  Resolve the OpenRouter API key from environment variables.

  Priority: CERBERUS_API_KEY > CERBERUS_OPENROUTER_API_KEY > OPENROUTER_API_KEY
  """
  @spec resolve_api_key() :: {:ok, String.t()} | :error
  def resolve_api_key do
    key =
      System.get_env("CERBERUS_API_KEY") ||
        System.get_env("CERBERUS_OPENROUTER_API_KEY") ||
        System.get_env("OPENROUTER_API_KEY")

    if is_nil(key) or key == "", do: :error, else: {:ok, key}
  end

  @doc """
  Make a single LLM call to OpenRouter.

  Params: `%{model, messages, max_tokens}` with optional `tools`, `temperature`,
  `response_format`.

  Options: `receive_timeout` (default 120s), `user_agent_suffix` (default "reviewer").
  """
  @spec call(map(), keyword()) :: {:ok, map()} | {:error, term()}
  def call(params, opts \\ []) do
    case resolve_api_key() do
      :error -> {:error, :no_api_key}
      {:ok, key} -> do_call(key, params, opts)
    end
  end

  defp do_call(api_key, params, opts) do
    timeout = Keyword.get(opts, :receive_timeout, 120_000)
    suffix = Keyword.get(opts, :user_agent_suffix, "reviewer")

    payload =
      %{model: params.model, messages: params.messages, max_tokens: params[:max_tokens] || 4096}
      |> maybe_put(:tools, params[:tools])
      |> maybe_put(:temperature, params[:temperature])
      |> maybe_put(:response_format, params[:response_format])

    case Req.post(@url,
           json: payload,
           headers: [
             {"authorization", "Bearer #{api_key}"},
             {"user-agent", "cerberus-#{suffix}/1.0"},
             {"http-referer", "https://github.com/misty-step/cerberus"},
             {"x-title", "Cerberus #{String.capitalize(suffix)}"}
           ],
           receive_timeout: timeout
         ) do
      {:ok, %{status: 200, body: body}} ->
        parse_response(body)

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

  defp parse_response(body) when is_map(body) do
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

  defp parse_response(_), do: {:error, :invalid_response}

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

  defp maybe_put(map, _key, nil), do: map
  defp maybe_put(map, _key, []), do: map
  defp maybe_put(map, key, val), do: Map.put(map, key, val)
end
