defmodule Cerberus.Application do
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    port = Application.get_env(:cerberus_elixir, :api_port, 4000)

    children = [
      Cerberus.Config,
      {Cerberus.Store, database_path: Cerberus.database_path()},
      Cerberus.ReviewSupervisor,
      Cerberus.Router,
      Cerberus.Telemetry,
      {Bandit, plug: Cerberus.API, port: port}
    ]

    opts = [strategy: :one_for_one, name: Cerberus.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
