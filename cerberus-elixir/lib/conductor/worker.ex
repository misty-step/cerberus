defmodule Conductor.Worker do
  @moduledoc false

  @callback perform(map(), keyword()) :: {:ok, term()} | {:error, term()}
end
