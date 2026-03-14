defmodule Cerberus.BB.Worker do
  @moduledoc false

  @behaviour Conductor.Worker

  @impl true
  def perform(_payload, _opts) do
    {:ok, :stub}
  end
end
