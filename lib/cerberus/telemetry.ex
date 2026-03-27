defmodule Cerberus.Telemetry do
  @moduledoc """
  OpenTelemetry instrumentation and Langfuse export for Cerberus review runs.

  Creates a trace hierarchy per review run:

      review_run → reviewer (×N) → llm_call (×M)

  Each LLM call span carries GenAI semantic conventions (model, tokens, cost).
  When LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set, reviewer completion
  events are also exported to Langfuse via REST API.

  ## Span helpers

      Cerberus.Telemetry.with_review_run(42, fn ctx ->
        Cerberus.Telemetry.with_reviewer(ctx, :correctness, model, fn ->
          Cerberus.Telemetry.with_llm_call(model, fn ->
            Cerberus.LLM.OpenRouter.call(params)
          end)
        end)
      end)

  The `ctx` token propagates parent-child relationships across GenServer
  process boundaries — pass it from the orchestrator to each reviewer.
  """

  use GenServer
  require Logger
  require OpenTelemetry.Tracer, as: Tracer

  # --- Client API ---

  def start_link(opts \\ []) do
    {name, opts} = Keyword.pop(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, [{:server_name, name} | opts], name: name)
  end

  @doc """
  Wrap a function in a review run root trace.

  The callback receives the current OpenTelemetry context for propagation
  to child spans in other processes (e.g., reviewer GenServers).
  """
  def with_review_run(pr_number, fun) when is_function(fun, 1) do
    Tracer.with_span :"cerberus.review_run", %{
      attributes: [{"cerberus.pr_number", pr_number}]
    } do
      fun.(OpenTelemetry.Ctx.get_current())
    end
  end

  @doc """
  Wrap a reviewer execution in a child span.

  Attaches `parent_ctx` before creating the span so the reviewer span
  appears as a child of the review run trace, even across process boundaries.
  On success, sets GenAI usage attributes and calculated cost.
  """
  def with_reviewer(parent_ctx, perspective, model, fun) when is_function(fun, 0) do
    token = if parent_ctx, do: OpenTelemetry.Ctx.attach(parent_ctx), else: nil

    try do
      Tracer.with_span :"cerberus.reviewer", %{
        attributes: [
          {"cerberus.perspective", to_string(perspective)},
          {"gen_ai.request.model", to_string(model)}
        ]
      } do
        result = fun.()
        set_reviewer_result_attrs(result, model)
        result
      end
    after
      if token, do: OpenTelemetry.Ctx.detach(token)
    end
  end

  @doc """
  Wrap an LLM call in a span with GenAI semantic conventions.

  Sets `gen_ai.system`, `gen_ai.operation.name`, `gen_ai.request.model`
  on entry, and `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens`
  on completion.
  """
  def with_llm_call(model, fun) when is_function(fun, 0) do
    Tracer.with_span :"gen_ai.chat", %{
      attributes: [
        {"gen_ai.system", "openrouter"},
        {"gen_ai.operation.name", "chat"},
        {"gen_ai.request.model", to_string(model)}
      ]
    } do
      result = fun.()
      set_llm_result_attrs(result)
      result
    end
  end

  @doc "Whether Langfuse export is active for this telemetry instance."
  def langfuse_configured?(server \\ __MODULE__) do
    GenServer.call(server, :langfuse_configured?)
  end

  # --- GenServer ---

  @impl true
  def init(opts) do
    name = Keyword.get(opts, :server_name, __MODULE__)
    langfuse = resolve_langfuse(opts)
    handler_ids = attach_handlers(name, langfuse)
    {:ok, %{langfuse: langfuse, handler_ids: handler_ids}}
  end

  @impl true
  def handle_call(:langfuse_configured?, _from, state) do
    {:reply, state.langfuse.enabled, state}
  end

  @impl true
  def terminate(_reason, state) do
    Enum.each(state.handler_ids, &:telemetry.detach/1)
    :ok
  end

  # --- Telemetry Handler Registration ---

  defp attach_handlers(name, langfuse) do
    prefix = "cerberus-otel-#{:erlang.phash2(name)}"

    complete_id = "#{prefix}-reviewer-complete"
    error_id = "#{prefix}-reviewer-error"

    :telemetry.attach(
      complete_id,
      [:cerberus, :reviewer, :complete],
      &__MODULE__.handle_reviewer_complete/4,
      langfuse
    )

    :telemetry.attach(
      error_id,
      [:cerberus, :reviewer, :error],
      &__MODULE__.handle_reviewer_error/4,
      langfuse
    )

    [complete_id, error_id]
  end

  # --- Telemetry Event Handlers ---

  @doc false
  def handle_reviewer_complete(_event, measurements, metadata, langfuse) do
    if langfuse.enabled do
      model_str = to_string(metadata.model)

      cost =
        Cerberus.Verdict.Cost.calculate(
          measurements.prompt_tokens,
          measurements.completion_tokens,
          model_str
        )

      Cerberus.Telemetry.Langfuse.send_generation(langfuse, %{
        name: "reviewer.#{metadata.perspective}",
        model: model_str,
        input_tokens: measurements.prompt_tokens,
        output_tokens: measurements.completion_tokens,
        duration_ms: measurements.duration_ms,
        status: "success",
        cost: cost
      })
    end
  end

  @doc false
  def handle_reviewer_error(_event, measurements, metadata, langfuse) do
    if langfuse.enabled do
      Cerberus.Telemetry.Langfuse.send_generation(langfuse, %{
        name: "reviewer.#{metadata.perspective}",
        model: to_string(metadata.model),
        duration_ms: measurements.duration_ms,
        status: "error"
      })
    end
  end

  # --- Span Attribute Helpers ---

  defp set_reviewer_result_attrs({:ok, %{verdict: v, usage: u}}, model) do
    cost =
      Cerberus.Verdict.Cost.calculate(
        u.prompt_tokens,
        u.completion_tokens,
        to_string(model)
      )

    Tracer.set_attributes([
      {"gen_ai.usage.input_tokens", u.prompt_tokens},
      {"gen_ai.usage.output_tokens", u.completion_tokens},
      {"gen_ai.usage.cost", cost},
      {"cerberus.verdict", v.verdict}
    ])
  end

  defp set_reviewer_result_attrs(_, _), do: :ok

  defp set_llm_result_attrs({:ok, %{usage: u}}) when is_map(u) do
    Tracer.set_attributes([
      {"gen_ai.usage.input_tokens", u[:prompt_tokens] || 0},
      {"gen_ai.usage.output_tokens", u[:completion_tokens] || 0}
    ])
  end

  defp set_llm_result_attrs(_), do: :ok

  # --- Langfuse Config Resolution ---

  defp resolve_langfuse(opts) do
    pk =
      Keyword.get(opts, :langfuse_public_key) ||
        Application.get_env(:cerberus_elixir, :langfuse_public_key)

    sk =
      Keyword.get(opts, :langfuse_secret_key) ||
        Application.get_env(:cerberus_elixir, :langfuse_secret_key)

    host =
      Keyword.get(opts, :langfuse_host) ||
        Application.get_env(:cerberus_elixir, :langfuse_host) ||
        "https://cloud.langfuse.com"

    %{
      enabled: is_binary(pk) and pk != "" and is_binary(sk) and sk != "",
      public_key: pk,
      secret_key: sk,
      host: host
    }
  end
end
