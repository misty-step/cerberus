defmodule Cerberus.Router do
  @moduledoc false

  use GenServer

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @impl true
  def init(opts) do
    {:ok, %{config: Keyword.fetch!(opts, :config)}}
  end
end
