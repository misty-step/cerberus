defmodule Cerberus.Config.Persona do
  @moduledoc """
  A named reviewer identity: perspective + prompt + model policy.

  Invariants:
  - `name` is unique across the bench (e.g. "trace", "guard")
  - `perspective` maps to a system prompt file (e.g. :correctness → pi/agents/correctness.md)
  - `prompt` is the full text of the system prompt, never empty
  - `model_policy` is :pool (random from wave pool) or a specific model string
  """

  @enforce_keys [:name, :perspective, :prompt, :model_policy]
  defstruct [
    :name,
    :perspective,
    :prompt,
    :model_policy,
    :description,
    :override,
    tools: %{}
  ]

  @type t :: %__MODULE__{
          name: String.t(),
          perspective: atom(),
          prompt: String.t(),
          model_policy: :pool | String.t(),
          description: String.t() | nil,
          override: atom() | nil,
          tools: map()
        }
end
