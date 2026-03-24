defmodule Cerberus.LocalRepoReadHandlerTest do
  use ExUnit.Case, async: true

  alias Cerberus.Tools.LocalRepoReadHandler

  defp with_temp_repo(fun) do
    repo_root =
      Path.join(System.tmp_dir!(), "cerberus_local_repo_#{System.unique_integer([:positive])}")

    try do
      File.mkdir_p!(repo_root)
      fun.(repo_root)
    after
      File.rm_rf(repo_root)
    end
  end

  defp write_sample!(repo_root, relative_path, content) do
    path = Path.join(repo_root, relative_path)
    File.mkdir_p!(Path.dirname(path))
    File.write!(path, content)
    path
  end

  test "search_code treats dash-prefixed queries as literals" do
    with_temp_repo(fn repo_root ->
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
    end)
  end

  test "search_code falls back to grep when rg is unavailable" do
    grep = System.find_executable("grep")
    assert is_binary(grep)

    with_temp_repo(fn repo_root ->
      lib_dir = Path.join(repo_root, "lib")
      File.mkdir_p!(lib_dir)
      File.write!(Path.join(lib_dir, "sample.ex"), "defmodule Sample do\n  @tag \"-n\"\nend\n")

      handler = LocalRepoReadHandler.build(repo_root, rg: nil, grep: grep)

      assert {:ok, output} =
               handler.(%{
                 name: "search_code",
                 arguments: %{"query" => "-n"}
               })

      assert output =~ "lib/sample.ex"
    end)
  end

  test "search_code grep fallback does not follow symlinks outside the repo root" do
    grep = System.find_executable("grep")
    assert is_binary(grep)

    with_temp_repo(fn repo_root ->
      outside_root =
        Path.join(System.tmp_dir!(), "cerberus_outside_dir_#{System.unique_integer([:positive])}")

      try do
        File.mkdir_p!(Path.join(repo_root, "inside"))
        File.mkdir_p!(outside_root)
        File.write!(Path.join(outside_root, "secret.txt"), "needle\n")
        File.ln_s!(outside_root, Path.join(repo_root, "inside/outside-link"))

        handler = LocalRepoReadHandler.build(repo_root, rg: nil, grep: grep)

        assert {:ok, "No results found for: needle"} =
                 handler.(%{
                   name: "search_code",
                   arguments: %{"query" => "needle"}
                 })
      after
        File.rm_rf(outside_root)
      end
    end)
  end

  test "get_file_contents rejects absolute and traversal paths" do
    with_temp_repo(fn repo_root ->
      handler = LocalRepoReadHandler.build(repo_root)

      assert {:error, message} =
               handler.(%{
                 name: "get_file_contents",
                 arguments: %{"path" => "/etc/passwd"}
               })

      assert message =~ "Invalid path"

      assert {:error, message} =
               handler.(%{
                 name: "get_file_contents",
                 arguments: %{"path" => "../../../../../etc/passwd"}
               })

      assert message =~ "Invalid path"
    end)
  end

  test "get_file_contents rejects symlink escapes outside the repo root" do
    with_temp_repo(fn repo_root ->
      outside_path =
        Path.join(System.tmp_dir!(), "cerberus_outside_#{System.unique_integer([:positive])}.txt")

      try do
        File.write!(outside_path, "do not read")
        write_sample!(repo_root, "safe/inside.txt", "allowed")
        File.ln_s!(outside_path, Path.join(repo_root, "safe/outside-link"))

        handler = LocalRepoReadHandler.build(repo_root)

        assert {:ok, "allowed"} =
                 handler.(%{
                   name: "get_file_contents",
                   arguments: %{"path" => "safe/inside.txt"}
                 })

        assert {:error, message} =
                 handler.(%{
                   name: "get_file_contents",
                   arguments: %{"path" => "safe/outside-link"}
                 })

        assert message =~ "Invalid path"
      after
        File.rm(outside_path)
      end
    end)
  end

  test "get_file_contents rejects symlink cycles" do
    with_temp_repo(fn repo_root ->
      File.mkdir_p!(Path.join(repo_root, "safe"))
      File.ln_s!("loop", Path.join(repo_root, "safe/loop"))
      eloop_message = List.to_string(:file.format_error(:eloop))

      handler = LocalRepoReadHandler.build(repo_root)

      assert {:error, message} =
               handler.(%{
                 name: "get_file_contents",
                 arguments: %{"path" => "safe/loop"}
               })

      assert message =~ eloop_message
    end)
  end

  test "list_directory rejects traversal outside the repo root" do
    with_temp_repo(fn repo_root ->
      handler = LocalRepoReadHandler.build(repo_root)

      assert {:error, message} =
               handler.(%{
                 name: "list_directory",
                 arguments: %{"path" => "../../.."}
               })

      assert message =~ "Invalid path"
    end)
  end

  test "list_directory rejects symlink cycles" do
    with_temp_repo(fn repo_root ->
      File.mkdir_p!(Path.join(repo_root, "safe"))
      File.ln_s!("loop", Path.join(repo_root, "safe/loop"))
      eloop_message = List.to_string(:file.format_error(:eloop))

      handler = LocalRepoReadHandler.build(repo_root)

      assert {:error, message} =
               handler.(%{
                 name: "list_directory",
                 arguments: %{"path" => "safe/loop"}
               })

      assert message =~ eloop_message
    end)
  end
end
