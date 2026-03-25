defmodule Cerberus.Engine do
  @moduledoc """
  Infrastructure-agnostic review execution core.

  Accepts a diff plus normalized review context, routes the change to the
  minimum reviewer panel, runs reviewers in parallel, and returns the
  aggregated review result together with per-reviewer execution records.

  ## DI seams (all via `opts`)

      :config_server     — Config GenServer (default: Cerberus.Config)
      :router_server     — Router GenServer (default: Cerberus.Router)
      :supervisor        — DynamicSupervisor for reviewers (default: Cerberus.ReviewSupervisor)
      :call_llm          — LLM function passed to each Reviewer
      :tool_handler      — tool handler passed to each Reviewer
      :task_supervisor   — TaskSupervisor for reviewer tasks (default: Cerberus.TaskSupervisor)
      :reviewer_timeout  — per-reviewer timeout in ms (default: 600_000)
      :repo_root         — for template loading
      :routing_metadata  — metadata forwarded to Router.route/3
      :override          — optional override data applied during aggregation
  """

  alias Cerberus.Verdict

  defmodule ReviewerExecution do
    @moduledoc false

    @enforce_keys [:reviewer, :perspective, :verdict, :usage, :model, :status]
    defstruct [:reviewer, :perspective, :verdict, :usage, :model, :status]

    @type t :: %__MODULE__{
            reviewer: String.t(),
            perspective: String.t(),
            verdict: Verdict.t(),
            usage: %{prompt_tokens: non_neg_integer(), completion_tokens: non_neg_integer()},
            model: String.t(),
            status: :ok | :error | :timeout
          }
  end

  defmodule Result do
    @moduledoc false

    @enforce_keys [
      :verdict,
      :summary,
      :reviewers,
      :findings,
      :override,
      :reserves,
      :stats,
      :cost,
      :reviewer_results
    ]
    defstruct [
      :verdict,
      :summary,
      :reviewers,
      :findings,
      :override,
      :reserves,
      :stats,
      :cost,
      :reviewer_results
    ]

    @type t :: %__MODULE__{
            verdict: String.t(),
            summary: String.t(),
            reviewers: [Verdict.t()],
            findings: [map()],
            override: map() | nil,
            reserves: [atom()],
            stats: map(),
            cost: %{total_usd: float(), per_reviewer: %{String.t() => float()}},
            reviewer_results: [ReviewerExecution.t()]
          }
  end

  @doc """
  Execute the review core against provided diff/context inputs.

  Returns an aggregated result plus the reviewer execution records needed by
  orchestration layers that persist reviewer artifacts separately.
  """
  @spec review(String.t(), map(), keyword()) :: {:ok, Result.t()}
  def review(diff, context, opts \\ []) when is_binary(diff) and is_map(context) do
    Cerberus.Review.review(diff, context, opts)
  end
end
