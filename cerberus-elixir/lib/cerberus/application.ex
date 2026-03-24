defmodule Cerberus.Application do
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    port = Application.get_env(:cerberus_elixir, :api_port, 4000)

    children = [
      Cerberus.Config,
      {Cerberus.Store, name: Cerberus.Store, database_path: Cerberus.database_path()},
      {DynamicSupervisor, name: Cerberus.ReviewSupervisor, strategy: :one_for_one},
      {Task.Supervisor, name: Cerberus.TaskSupervisor},
      Cerberus.Router,
      Cerberus.Telemetry,
      {Bandit, plug: {Cerberus.API, pipeline: &Cerberus.Pipeline.start/2}, port: port}
    ]

    opts = [strategy: :one_for_one, name: Cerberus.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
