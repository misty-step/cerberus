defmodule Cerberus.CommandTest do
  use ExUnit.Case, async: true

  alias Cerberus.Command

  test "execute/1 prints top-level help with only the review inventory" do
    assert {:ok, %{output: output, exit_code: 0}} = Command.execute(["--help"])

    assert output =~ "Usage:"
    assert output =~ "cerberus review --repo <path> --base <ref> --head <ref>"
    assert output =~ "Commands:"
    assert output =~ "review"
    refute output =~ "init"
    refute output =~ "start"
    refute output =~ "server"
    refute output =~ "migrate"
  end

  test "execute/1 rejects retired commands with actionable guidance" do
    for command <- ~w(init start server migrate) do
      assert {:error, %{message: message, exit_code: 1}} = Command.execute([command])
      assert message =~ "Command `#{command}` has been retired."
      assert message =~ "cerberus review --repo <path> --base <ref> --head <ref>"
    end
  end
end
