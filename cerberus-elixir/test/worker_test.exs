defmodule Cerberus.BB.WorkerTest do
  use ExUnit.Case, async: true

  test "declares the conductor worker behaviour and exposes a stub perform callback" do
    behaviours = Cerberus.BB.Worker.module_info(:attributes)[:behaviour] || []

    assert Conductor.Worker in behaviours
    assert function_exported?(Cerberus.BB.Worker, :perform, 2)
    assert {:ok, :stub} = Cerberus.BB.Worker.perform(%{}, [])
  end
end
