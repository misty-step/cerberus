defmodule Cerberus.RouterTest do
  use ExUnit.Case, async: true

  alias Cerberus.Router

  @repo_root Path.expand("../../..", __DIR__)

  @simple_diff """
  diff --git a/lib/foo.ex b/lib/foo.ex
  --- a/lib/foo.ex
  +++ b/lib/foo.ex
  @@ -1,3 +1,5 @@
   defmodule Foo do
  +  def hello, do: :world
  +  def greet(n), do: "Hi " <> n
   end
  """

  @doc_only_diff """
  diff --git a/README.md b/README.md
  --- a/README.md
  +++ b/README.md
  @@ -1,2 +1,4 @@
   # Project
  +
  +Added docs.
  """

  @security_diff """
  diff --git a/lib/auth/jwt.ex b/lib/auth/jwt.ex
  --- a/lib/auth/jwt.ex
  +++ b/lib/auth/jwt.ex
  @@ -1,3 +1,5 @@
   defmodule Auth.JWT do
  +  def verify(token), do: :ok
  +  def sign(claims), do: "token"
   end
  """

  # --- parse_diff/1 ---

  describe "parse_diff/1" do
    test "returns empty summary for nil" do
      summary = Router.parse_diff(nil)
      assert summary.total_files == 0
      assert summary.code_changed == false
    end

    test "returns empty summary for empty string" do
      summary = Router.parse_diff("")
      assert summary.total_files == 0
    end

    test "parses file paths and line counts from unified diff" do
      summary = Router.parse_diff(@simple_diff)
      assert summary.total_files == 1
      assert summary.total_additions == 2
      assert summary.total_deletions == 0
      assert summary.total_changed_lines == 2
      assert summary.code_changed == true

      [file] = summary.files
      assert file.path == "lib/foo.ex"
      assert file.additions == 2
      assert file.deletions == 0
      assert file.is_code == true
    end

    test "classifies doc files" do
      summary = Router.parse_diff(@doc_only_diff)
      assert summary.doc_files == 1
      assert summary.code_files == 0
      assert summary.code_changed == false
    end

    test "handles multi-file diffs" do
      diff = """
      diff --git a/lib/a.ex b/lib/a.ex
      --- a/lib/a.ex
      +++ b/lib/a.ex
      @@ -1,1 +1,2 @@
       defmodule A do
      +  def a, do: :a
      diff --git a/lib/b.ex b/lib/b.ex
      --- a/lib/b.ex
      +++ b/lib/b.ex
      @@ -1,1 +1,3 @@
       defmodule B do
      +  def b, do: :b
      +  def c, do: :c
      """

      summary = Router.parse_diff(diff)
      assert summary.total_files == 2
      assert summary.total_additions == 3
    end

    test "tracks extension histogram" do
      summary = Router.parse_diff(@simple_diff)
      assert summary.extensions[".ex"] == 1
    end
  end

  # --- classify_file/1 ---

  describe "classify_file/1" do
    test "classifies .md as doc" do
      assert Router.classify_file("README.md") == {true, false, false}
    end

    test "classifies docs/ paths as doc" do
      assert Router.classify_file("docs/guide.txt") == {true, false, false}
    end

    test "classifies test/ paths as test" do
      assert Router.classify_file("test/foo_test.exs") == {false, true, false}
    end

    test "classifies .test. files as test" do
      assert Router.classify_file("src/foo.test.js") == {false, true, false}
    end

    test "classifies .spec. files as test" do
      assert Router.classify_file("src/foo.spec.ts") == {false, true, false}
    end

    test "classifies code files" do
      assert Router.classify_file("lib/foo.ex") == {false, false, true}
      assert Router.classify_file("src/main.py") == {false, false, true}
    end

    test "unknown extensions default to code" do
      assert Router.classify_file("Makefile") == {false, false, true}
    end
  end

  # --- classify_size/1 ---

  describe "classify_size/1" do
    test "small for <= 50 lines" do
      assert Router.classify_size(%{total_changed_lines: 0}) == :small
      assert Router.classify_size(%{total_changed_lines: 50}) == :small
    end

    test "medium for 51-200 lines" do
      assert Router.classify_size(%{total_changed_lines: 51}) == :medium
      assert Router.classify_size(%{total_changed_lines: 200}) == :medium
    end

    test "large for 201-500 lines" do
      assert Router.classify_size(%{total_changed_lines: 201}) == :large
      assert Router.classify_size(%{total_changed_lines: 500}) == :large
    end

    test "xlarge for > 500 lines" do
      assert Router.classify_size(%{total_changed_lines: 501}) == :xlarge
    end
  end

  # --- classify_model_tier/1 ---

  describe "classify_model_tier/1" do
    test "flash for small doc/test-only changes" do
      summary = %{
        total_changed_lines: 10,
        code_files: 0,
        test_files: 1,
        doc_files: 1,
        files: []
      }

      assert Router.classify_model_tier(summary) == :flash
    end

    test "pro for large changes" do
      summary = %{
        total_changed_lines: 300,
        code_files: 5,
        test_files: 0,
        doc_files: 0,
        files: []
      }

      assert Router.classify_model_tier(summary) == :pro
    end

    test "pro for security-relevant paths" do
      summary = %{
        total_changed_lines: 10,
        code_files: 1,
        test_files: 0,
        doc_files: 0,
        files: [%{path: "lib/auth/handler.ex"}]
      }

      assert Router.classify_model_tier(summary) == :pro
    end

    test "standard for typical changes" do
      summary = %{
        total_changed_lines: 100,
        code_files: 3,
        test_files: 1,
        doc_files: 0,
        files: [%{path: "lib/foo.ex"}, %{path: "lib/bar.ex"}]
      }

      assert Router.classify_model_tier(summary) == :standard
    end
  end

  describe "parse_diff with security-relevant files" do
    test "security diff is classified as code with correct path" do
      summary = Router.parse_diff(@security_diff)
      assert summary.code_changed == true
      [file] = summary.files
      assert file.path == "lib/auth/jwt.ex"
    end

    test "security diff triggers pro model tier" do
      summary = Router.parse_diff(@security_diff)
      assert Router.classify_model_tier(summary) == :pro
    end
  end

  # --- route/3 (integration with Config) ---

  describe "route/3" do
    setup do
      config_name = :"config_router_#{System.unique_integer([:positive])}"
      {:ok, _config_pid} = Cerberus.Config.start_link(repo_root: @repo_root, name: config_name)

      # Mock LLM that returns a valid panel
      mock_llm = fn params ->
        panel_size = params.panel_size
        perspectives = params.all_perspectives

        panel =
          perspectives
          |> Enum.take(panel_size)

        {:ok, panel}
      end

      router_name = :"router_#{System.unique_integer([:positive])}"

      {:ok, _router_pid} =
        Router.start_link(
          name: router_name,
          config_server: config_name,
          call_llm: mock_llm
        )

      %{router: router_name, config: config_name, mock_llm: mock_llm}
    end

    test "returns panel with correct size", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert length(result.panel) == 4
    end

    test "panel contains only valid perspectives", %{router: router, config: config} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      valid = Cerberus.Config.personas(config) |> Enum.map(&to_string(&1.perspective))

      for p <- result.panel do
        assert p in valid, "#{p} not a valid perspective"
      end
    end

    test "reserves contain non-selected perspectives", %{router: router, config: config} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      all = Cerberus.Config.personas(config) |> Enum.map(&to_string(&1.perspective)) |> MapSet.new()
      panel_set = MapSet.new(result.panel)
      reserve_set = MapSet.new(result.reserves)

      assert MapSet.union(panel_set, reserve_set) == all
      assert MapSet.intersection(panel_set, reserve_set) == MapSet.new()
    end

    test "includes model_tier and size_bucket", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.model_tier in [:flash, :standard, :pro]
      assert result.size_bucket in [:small, :medium, :large, :xlarge]
    end

    test "trace (correctness) always included when code changed", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert "correctness" in result.panel
    end

    test "guard (security) included when code changed", %{router: router} do
      # Use a mock that returns exactly what the fallback would, to verify
      # the required perspectives are enforced
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert "security" in result.panel
    end

    test "routing_used reflects LLM success", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == true
    end
  end

  describe "route/3 fallback" do
    setup do
      config_name = :"config_fallback_#{System.unique_integer([:positive])}"
      {:ok, _config_pid} = Cerberus.Config.start_link(repo_root: @repo_root, name: config_name)

      # Mock LLM that always fails
      failing_llm = fn _params -> {:error, :api_unavailable} end

      router_name = :"router_fallback_#{System.unique_integer([:positive])}"

      {:ok, _router_pid} =
        Router.start_link(
          name: router_name,
          config_server: config_name,
          call_llm: failing_llm
        )

      %{router: router_name, config: config_name}
    end

    test "falls back to deterministic panel on LLM failure", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == false
      assert length(result.panel) == 4
    end

    test "fallback panel still includes required perspectives", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert "correctness" in result.panel
      assert "security" in result.panel
    end

    test "never crashes on LLM failure", %{router: router} do
      {:ok, _result} = Router.route(@simple_diff, [], router)
      {:ok, _result} = Router.route(@doc_only_diff, [], router)
      {:ok, _result} = Router.route("", [], router)
    end
  end

  describe "route/3 with invalid LLM response" do
    setup do
      config_name = :"config_invalid_#{System.unique_integer([:positive])}"
      {:ok, _config_pid} = Cerberus.Config.start_link(repo_root: @repo_root, name: config_name)

      # Mock LLM that returns wrong-sized panel
      bad_llm = fn _params -> {:ok, ["correctness", "security"]} end

      router_name = :"router_invalid_#{System.unique_integer([:positive])}"

      {:ok, _router_pid} =
        Router.start_link(
          name: router_name,
          config_server: config_name,
          call_llm: bad_llm
        )

      %{router: router_name}
    end

    test "falls back when LLM returns wrong panel size", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == false
      assert length(result.panel) == 4
    end
  end

  describe "route/3 doc-only PR" do
    setup do
      config_name = :"config_doc_#{System.unique_integer([:positive])}"
      {:ok, _config_pid} = Cerberus.Config.start_link(repo_root: @repo_root, name: config_name)

      mock_llm = fn params ->
        {:ok, Enum.take(params.all_perspectives, params.panel_size)}
      end

      router_name = :"router_doc_#{System.unique_integer([:positive])}"

      {:ok, _router_pid} =
        Router.start_link(
          name: router_name,
          config_server: config_name,
          call_llm: mock_llm
        )

      %{router: router_name}
    end

    test "classifies doc-only PR correctly", %{router: router} do
      {:ok, result} = Router.route(@doc_only_diff, [], router)
      assert result.model_tier == :flash
      assert result.size_bucket == :small
    end
  end
end
