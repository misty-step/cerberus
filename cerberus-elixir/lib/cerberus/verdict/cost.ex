defmodule Cerberus.Verdict.Cost do
  @moduledoc """
  Per-review cost calculation from token usage and model pricing.

  Pricing is configuration-driven. Unknown models fall back to a conservative
  default rate. The `openrouter/` prefix is stripped before lookup.
  """

  @default_pricing {0.50, 1.50}

  @model_pricing %{
    "google/gemini-3-flash-preview" => {0.50, 3.00},
    "moonshotai/kimi-k2.5" => {0.45, 2.20},
    "z-ai/glm-5" => {0.72, 2.30},
    "minimax/minimax-m2.5" => {0.27, 0.95},
    "x-ai/grok-4.1-fast" => {0.20, 0.50},
    "x-ai/grok-4.20-beta" => {2.00, 6.00},
    "x-ai/grok-4.20-multi-agent-beta" => {2.00, 6.00},
    "inception/mercury-2" => {0.25, 0.75}
  }

  @spec calculate(non_neg_integer(), non_neg_integer(), String.t()) :: float()
  def calculate(prompt_tokens, completion_tokens, model) do
    {input_rate, output_rate} = lookup_pricing(model)
    prompt_tokens / 1_000_000 * input_rate + completion_tokens / 1_000_000 * output_rate
  end

  defp lookup_pricing(model) do
    normalized = String.replace_prefix(model, "openrouter/", "")
    Map.get(@model_pricing, model, Map.get(@model_pricing, normalized, @default_pricing))
  end
end
