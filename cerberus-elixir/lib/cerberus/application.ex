defmodule Cerberus.Application do
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    {:ok, loaded_config} = Cerberus.Config.load()

    children = [
      {Cerberus.Store, database_path: Cerberus.database_path()},
      Cerberus.ReviewSupervisor,
      {Cerberus.Router, config: loaded_config},
      Cerberus.Telemetry
    ]

    opts = [strategy: :one_for_one, name: Cerberus.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
