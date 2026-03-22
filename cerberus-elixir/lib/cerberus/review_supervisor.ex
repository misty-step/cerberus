defmodule Cerberus.ReviewSupervisor do
  @moduledoc false

  use DynamicSupervisor

  def start_link(opts \\ []) do
    {name, opts} = Keyword.pop(opts, :name)

    if name do
      DynamicSupervisor.start_link(__MODULE__, opts, name: name)
    else
      DynamicSupervisor.start_link(__MODULE__, opts)
    end
  end

  @impl true
  def init(_opts) do
    DynamicSupervisor.init(strategy: :one_for_one)
  end
end
