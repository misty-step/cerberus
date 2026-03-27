defmodule Cerberus.Config.Diagnostic do
  @moduledoc false

  @enforce_keys [:source, :path, :reason]
  defstruct [:source, :path, :reason, :value]

  @type t :: %__MODULE__{
          source: String.t(),
          path: String.t(),
          reason: String.t(),
          value: term() | nil
        }

  @spec format(t()) :: String.t()
  def format(%__MODULE__{} = diagnostic) do
    suffix =
      case diagnostic.value do
        nil -> ""
        value -> " (got: #{inspect(value)})"
      end

    "[#{diagnostic.source}] #{diagnostic.path}: #{diagnostic.reason}#{suffix}"
  end
end
