defmodule Cerberus.Config.Persona do
  @moduledoc """
  A named reviewer identity with resolved prompt and template assets.

  Invariants:
  - `id` / `name` are unique across the bench (e.g. "trace", "guard")
  - `perspective` maps to a resolved system prompt asset
  - `prompt` and `template` are never empty
  - `model_policy` is `:pool` or a specific model id
  """

  @enforce_keys [:id, :name, :perspective, :prompt, :template, :model_policy]
  defstruct [
    :id,
    :name,
    :perspective,
    :prompt,
    :prompt_id,
    :prompt_path,
    :prompt_digest,
    :template,
    :template_id,
    :template_path,
    :template_digest,
    :model_policy,
    :model_id,
    :provider_id,
    :description,
    :override,
    tools: %{},
    sources: %{}
  ]

  @type t :: %__MODULE__{
          id: String.t(),
          name: String.t(),
          perspective: atom(),
          prompt: String.t(),
          prompt_id: String.t() | nil,
          prompt_path: String.t() | nil,
          prompt_digest: String.t() | nil,
          template: String.t(),
          template_id: String.t() | nil,
          template_path: String.t() | nil,
          template_digest: String.t() | nil,
          model_policy: :pool | String.t(),
          model_id: String.t() | nil,
          provider_id: String.t() | nil,
          description: String.t() | nil,
          override: atom() | nil,
          tools: map(),
          sources: map()
        }
end
