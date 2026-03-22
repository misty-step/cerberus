defmodule Cerberus.ApplicationTest do
  use ExUnit.Case, async: false

  test "starts the required supervision tree" do
    children =
      Cerberus.Supervisor
      |> Supervisor.which_children()
      |> Enum.map(fn {id, _pid, _type, _modules} -> id end)

    assert Cerberus.Config in children
    assert Cerberus.Store in children
    assert Cerberus.ReviewSupervisor in children
    assert Cerberus.Router in children
  end

  test "defines a unix release with runtime tools" do
    release =
      Mix.Project.config()
      |> Keyword.fetch!(:releases)
      |> Keyword.fetch!(:cerberus)

    assert release[:include_executables_for] == [:unix]
    assert release[:applications][:runtime_tools] == :permanent
    assert release[:steps] |> hd() == :assemble
    assert release[:steps] |> List.last() |> is_function(1)
  end
end
