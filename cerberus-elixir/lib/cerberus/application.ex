defmodule Cerberus.Application do
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    Supervisor.start_link(child_specs(:server), strategy: :one_for_one, name: Cerberus.Supervisor)
  end

  def child_specs(mode, opts \\ [])

  def child_specs(:server, opts) do
    port = Keyword.get(opts, :port, Application.get_env(:cerberus_elixir, :api_port, 4000))
    config_name = Keyword.get(opts, :config_name, Cerberus.Config)
    store_name = Keyword.get(opts, :store_name, Cerberus.Store)
    review_supervisor_name = Keyword.get(opts, :review_supervisor_name, Cerberus.ReviewSupervisor)
    task_supervisor_name = Keyword.get(opts, :task_supervisor_name, Cerberus.TaskSupervisor)
    router_name = Keyword.get(opts, :router_name, Cerberus.Router)
    repo_root = Keyword.get(opts, :repo_root, Cerberus.repo_root())
    database_path = Keyword.get(opts, :database_path, Cerberus.database_path())

    [
      {Cerberus.Config, [name: config_name, repo_root: repo_root]},
      {Cerberus.Store, [name: store_name, database_path: database_path]},
      {Cerberus.ReviewSupervisor, [name: review_supervisor_name]},
      {Task.Supervisor, name: task_supervisor_name},
      {Cerberus.Router, [name: router_name, config_server: config_name]},
      Cerberus.Telemetry,
      {Bandit, plug: {Cerberus.API, pipeline: &Cerberus.Pipeline.start/2}, port: port}
    ]
  end

  def child_specs(:cli, opts) do
    config_name = Keyword.get(opts, :config_name, Cerberus.Config)
    review_supervisor_name = Keyword.get(opts, :review_supervisor_name, Cerberus.ReviewSupervisor)
    task_supervisor_name = Keyword.get(opts, :task_supervisor_name, Cerberus.TaskSupervisor)
    router_name = Keyword.get(opts, :router_name, Cerberus.Router)
    repo_root = Keyword.get(opts, :repo_root, Cerberus.repo_root())

    router_opts =
      [name: router_name, config_server: config_name]
      |> maybe_put(:call_llm, Keyword.get(opts, :router_call_llm))

    [
      {Cerberus.Config, [name: config_name, repo_root: repo_root]},
      {Cerberus.ReviewSupervisor, [name: review_supervisor_name]},
      {Task.Supervisor, name: task_supervisor_name},
      {Cerberus.Router, router_opts}
    ]
  end

  defp maybe_put(opts, _key, nil), do: opts
  defp maybe_put(opts, key, value), do: Keyword.put(opts, key, value)
end
