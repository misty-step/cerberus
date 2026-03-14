defmodule Cerberus.ApplicationTest do
  use ExUnit.Case, async: false

  test "starts the required supervision tree" do
    children =
      Cerberus.Supervisor
      |> Supervisor.which_children()
      |> Enum.map(fn {id, _pid, _type, _modules} -> id end)

    assert Cerberus.Store in children
    assert Cerberus.ReviewSupervisor in children
    assert Cerberus.Router in children
  end
end
