defmodule Cerberus.Telemetry.Langfuse do
  @moduledoc """
  Lightweight Langfuse REST client for exporting LLM generation traces.

  Sends data asynchronously — errors are logged, never raised. All calls
  are fire-and-forget via `Task.start/1` to avoid blocking the review pipeline.

  ## Authentication

  Uses HTTP Basic auth with `public_key:secret_key`, matching the Langfuse
  API convention.
  """

  require Logger

  @doc """
  Send an LLM generation record to Langfuse.

  Required attrs: `:name`, `:model`, `:status`.
  Optional: `:input_tokens`, `:output_tokens`, `:duration_ms`, `:cost`.
  """
  def send_generation(config, attrs) do
    body = %{
      name: attrs[:name],
      model: attrs[:model],
      startTime: DateTime.utc_now() |> DateTime.to_iso8601(),
      usage: %{
        input: attrs[:input_tokens] || 0,
        output: attrs[:output_tokens] || 0
      },
      metadata: %{
        duration_ms: attrs[:duration_ms],
        status: to_string(attrs[:status]),
        cost_usd: attrs[:cost]
      }
    }

    post_async(config, "/api/public/generations", body)
  end

  @doc """
  Send a trace record to Langfuse.

  Required attrs: `:name`. All other attrs are stored as metadata.
  """
  def send_trace(config, attrs) do
    body = %{
      name: attrs[:name],
      metadata: Map.drop(attrs, [:name])
    }

    post_async(config, "/api/public/traces", body)
  end

  # --- HTTP ---

  defp post_async(config, path, body) do
    Task.start(fn -> post(config, path, body) end)
  end

  @doc false
  def post(config, path, body) do
    url = config.host <> path
    auth = Base.encode64("#{config.public_key}:#{config.secret_key}")

    case Req.post(url,
           json: body,
           headers: [
             {"authorization", "Basic #{auth}"},
             {"content-type", "application/json"}
           ],
           receive_timeout: 10_000
         ) do
      {:ok, %{status: status}} when status in 200..299 ->
        :ok

      {:ok, %{status: status, body: resp_body}} ->
        Logger.warning("Langfuse POST #{path} returned #{status}: #{inspect(resp_body)}")
        {:error, {:http_error, status}}

      {:error, reason} ->
        Logger.warning("Langfuse POST #{path} failed: #{inspect(reason)}")
        {:error, reason}
    end
  end
end
