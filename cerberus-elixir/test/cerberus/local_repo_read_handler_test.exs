defmodule Cerberus.LocalRepoReadHandlerTest do
  use ExUnit.Case, async: true

  alias Cerberus.Tools.LocalRepoReadHandler

  test "search_code treats dash-prefixed queries as literals" do
    repo_root =
      Path.join(System.tmp_dir!(), "cerberus_local_repo_#{System.unique_integer([:positive])}")

    try do
      lib_dir = Path.join(repo_root, "lib")
      File.mkdir_p!(lib_dir)
      File.write!(Path.join(lib_dir, "sample.ex"), "defmodule Sample do\n  @tag \"-n\"\nend\n")

      handler = LocalRepoReadHandler.build(repo_root)

      assert {:ok, output} =
               handler.(%{
                 name: "search_code",
                 arguments: %{"query" => "-n"}
               })

      assert output =~ "lib/sample.ex"
    after
      File.rm_rf(repo_root)
    end
  end
end
