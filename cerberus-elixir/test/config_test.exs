defmodule Cerberus.ConfigTest do
  use ExUnit.Case, async: true

  test "loads defaults config and persona prompts from the repository" do
    assert {:ok, config} = Cerberus.Config.load(repo_root: Path.expand("..", __DIR__))

    assert get_in(config, ["defaults", "name"]) == "Cerberus"
    assert Map.has_key?(config["prompts"], "correctness")
    assert String.contains?(config["prompts"]["correctness"], "correctness")
  end
end
