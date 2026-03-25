defmodule Cerberus.ApplicationTest do
  use ExUnit.Case, async: false

  test "starts the required supervision tree" do
    children =
      Cerberus.Supervisor
      |> Supervisor.which_children()
      |> Enum.map(fn {id, _pid, _type, _modules} -> id end)

    assert Cerberus.Config in children
    assert Cerberus.ReviewSupervisor in children
    assert Cerberus.TaskSupervisor in children
    assert Cerberus.Router in children
    assert is_pid(Process.whereis(Cerberus.ReviewSupervisor))
    refute Enum.any?(children, &match?(Cerberus.Store, &1))
    refute Enum.any?(children, &match?(Cerberus.API, &1))

    assert %{supervisors: 0, workers: 0} =
             DynamicSupervisor.count_children(Cerberus.ReviewSupervisor)
  end

  test "defines an escript entrypoint for the CLI-only command surface" do
    escript = Mix.Project.config() |> Keyword.fetch!(:escript)

    assert escript[:main_module] == Cerberus.Command
    assert escript[:name] == "cerberus"
  end
end
