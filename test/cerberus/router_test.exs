defmodule Cerberus.RouterTest do
  use ExUnit.Case, async: true

  alias Cerberus.Router

  @repo_root Path.expand("../..", __DIR__)

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

  @test_only_diff """
  diff --git a/test/sample_test.exs b/test/sample_test.exs
  --- a/test/sample_test.exs
  +++ b/test/sample_test.exs
  @@ -1,3 +1,5 @@
   defmodule SampleTest do
  +  test "returns ok" do
  +    assert :ok == :ok
  +  end
   end
  """

  @repo_aware_diff """
  diff --git a/lib/service.ex b/lib/service.ex
  --- a/lib/service.ex
  +++ b/lib/service.ex
  @@ -1,3 +1,5 @@
   defmodule Service do
  +  def call(arg), do: {:ok, arg}
  +  def ready?, do: true
   end
  """

  @narrow_diff """
  diff --git a/lib/billing.ex b/lib/billing.ex
  --- a/lib/billing.ex
  +++ b/lib/billing.ex
  @@ -1,3 +1,9 @@
   defmodule Billing do
  +  def create(a), do: {:ok, a}
  +  def update(a), do: {:ok, a}
  +  def cancel(a), do: {:ok, a}
  +  def refund(a), do: {:ok, a}
  +  def capture(a), do: {:ok, a}
  +  def sync(a), do: {:ok, a}
   end
  """

  @broad_diff """
  diff --git a/lib/billing.ex b/lib/billing.ex
  --- a/lib/billing.ex
  +++ b/lib/billing.ex
  @@ -1,2 +1,4 @@
   defmodule Billing do
  +  def create(a), do: {:ok, a}
  +  def refund(a), do: {:ok, a}
   end
  diff --git a/config/runtime.exs b/config/runtime.exs
  --- a/config/runtime.exs
  +++ b/config/runtime.exs
  @@ -1,2 +1,4 @@
   import Config
  +config :billing, retries: 3
  +config :billing, timeout_ms: 5000
  diff --git a/test/billing_test.exs b/test/billing_test.exs
  --- a/test/billing_test.exs
  +++ b/test/billing_test.exs
  @@ -1,2 +1,4 @@
   defmodule BillingTest do
  +  test "creates a charge", do: assert(true)
  +  test "refunds a charge", do: assert(true)
   end
  """

  defp unique_name(prefix), do: :"#{prefix}_#{System.unique_integer([:positive])}"

  defp start_config!(overrides \\ %{}) do
    config_name = unique_name("config_router")

    {:ok, _config_pid} =
      Cerberus.Config.start_link(
        repo_root: @repo_root,
        name: config_name,
        config_overrides: overrides
      )

    config_name
  end

  defp start_router!(config_name, call_llm) do
    router_name = unique_name("router")

    {:ok, _router_pid} =
      Router.start_link(
        name: router_name,
        config_server: config_name,
        call_llm: call_llm
      )

    router_name
  end

  defp create_repo_fixture!(files) do
    root =
      Path.join(
        System.tmp_dir!(),
        "cerberus_router_repo_#{System.unique_integer([:positive])}"
      )

    Enum.each(files, fn {relative_path, content} ->
      path = Path.join(root, relative_path)
      File.mkdir_p!(Path.dirname(path))
      File.write!(path, content)
    end)

    root
  end

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

  describe "parse_diff with deleted files" do
    test "preserves original path when +++ /dev/null" do
      diff = """
      diff --git a/lib/old.ex b/lib/old.ex
      --- a/lib/old.ex
      +++ /dev/null
      @@ -1,3 +0,0 @@
      -defmodule Old do
      -  def gone, do: :bye
      -end
      """

      summary = Router.parse_diff(diff)
      assert summary.total_files == 1
      [file] = summary.files
      assert file.path == "lib/old.ex"
      assert file.deletions == 3
    end

    test "handles multiple deleted files without collision" do
      diff = """
      diff --git a/lib/a.ex b/lib/a.ex
      --- a/lib/a.ex
      +++ /dev/null
      @@ -1,2 +0,0 @@
      -defmodule A do
      -end
      diff --git a/lib/b.ex b/lib/b.ex
      --- a/lib/b.ex
      +++ /dev/null
      @@ -1,2 +0,0 @@
      -defmodule B do
      -end
      """

      summary = Router.parse_diff(diff)
      assert summary.total_files == 2
      paths = Enum.map(summary.files, & &1.path) |> Enum.sort()
      assert paths == ["lib/a.ex", "lib/b.ex"]
    end
  end

  # --- route/3 (integration with Config) ---

  describe "route/3" do
    setup do
      config_name = start_config!()

      # Deterministic mock that always returns required reviewer ids first
      preferred = ["trace", "guard", "atlas", "proof"]

      mock_llm = fn params ->
        {:ok, Enum.take(preferred, params.panel_size)}
      end

      router_name = start_router!(config_name, mock_llm)

      %{router: router_name, config: config_name, mock_llm: mock_llm}
    end

    test "returns panel with correct size", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert length(result.panel) == 3
    end

    test "panel contains only valid reviewer ids", %{router: router, config: config} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      valid = Cerberus.Config.personas(config) |> Enum.map(& &1.id)

      for p <- result.panel do
        assert p in valid, "#{p} not a valid reviewer id"
      end
    end

    test "reserves contain non-selected reviewer ids", %{router: router, config: config} do
      {:ok, result} = Router.route(@simple_diff, [], router)

      all =
        Cerberus.Config.personas(config) |> Enum.map(& &1.id) |> MapSet.new()

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

    test "trace reviewer always included when code changed", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert "trace" in result.panel
    end

    test "guard reviewer included when code changed", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert "guard" in result.panel
    end

    test "routing_used reflects LLM success", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == true
    end

    test "includes planner_trace with selected team and eligible bench", %{
      router: router,
      config: config
    } do
      {:ok, result} = Router.route(@simple_diff, [], router)
      active_bench = Cerberus.Config.personas(config) |> Enum.map(& &1.id)

      assert result.planner_trace.selected_team == result.panel
      assert result.planner_trace.eligible_bench == ["trace", "atlas", "guard", "craft"]
      assert Enum.all?(result.planner_trace.eligible_bench, &(&1 in active_bench))
      assert result.planner_trace.fallback.used == false
      assert result.planner_trace.diff_classification.doc_only == false
      assert result.planner_trace.diff_classification.broad_change == false
    end
  end

  describe "route/3 fallback" do
    setup do
      config_name = start_config!()

      # Mock LLM that always fails
      failing_llm = fn _params -> {:error, :api_unavailable} end

      router_name = start_router!(config_name, failing_llm)

      %{router: router_name, config: config_name}
    end

    test "falls back to deterministic panel on LLM failure", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == false
      assert length(result.panel) == 3
      assert result.planner_trace.fallback.used == true
      assert result.planner_trace.fallback.reason == "llm_error"
    end

    test "fallback panel still includes required reviewers", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert "trace" in result.panel
      assert "guard" in result.panel
    end

    test "never crashes on LLM failure", %{router: router} do
      {:ok, _result} = Router.route(@simple_diff, [], router)
      {:ok, _result} = Router.route(@doc_only_diff, [], router)
      {:ok, _result} = Router.route("", [], router)
    end
  end

  describe "route/3 with invalid LLM response" do
    setup do
      config_name = start_config!()

      # Mock LLM that returns wrong-sized panel
      bad_llm = fn _params -> {:ok, ["trace", "guard"]} end

      router_name = start_router!(config_name, bad_llm)

      %{router: router_name}
    end

    test "falls back when LLM returns wrong panel size", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == false
      assert length(result.panel) == 3
      assert result.planner_trace.fallback.reason == "invalid_panel"
    end
  end

  describe "route/3 doc-only PR" do
    setup do
      config_name = start_config!()

      mock_llm = fn params ->
        {:ok, Enum.take(params.all_reviewers, params.panel_size)}
      end

      router_name = start_router!(config_name, mock_llm)

      %{router: router_name}
    end

    test "classifies doc-only PR correctly", %{router: router} do
      {:ok, result} = Router.route(@doc_only_diff, [], router)
      assert result.model_tier == :flash
      assert result.size_bucket == :small
      assert length(result.panel) == 1
      assert result.planner_trace.diff_classification.doc_only == true
    end

    test "routes test-only changes to a smaller team than ordinary code", %{router: router} do
      {:ok, test_only} = Router.route(@test_only_diff, [], router)
      {:ok, code_change} = Router.route(@simple_diff, [], router)

      assert test_only.model_tier == :flash
      assert length(test_only.panel) < length(code_change.panel)
      assert test_only.planner_trace.diff_classification.test_only == true
      assert "proof" in test_only.planner_trace.eligible_bench
    end
  end

  describe "route/3 with nil routing model" do
    setup do
      config_name = start_config!()

      # Patch config to have nil model
      :sys.replace_state(config_name, fn state ->
        Map.update!(state, :routing, &Map.put(&1, :model, nil))
      end)

      # Mock LLM that captures the model it receives
      test_pid = self()

      mock_llm = fn params ->
        send(test_pid, {:llm_model, params.model})

        {:ok, Enum.take(["trace", "guard", "atlas", "proof"], params.panel_size)}
      end

      router_name = start_router!(config_name, mock_llm)

      %{router: router_name}
    end

    test "falls back to default router model when config model is nil", %{router: router} do
      {:ok, _result} = Router.route(@simple_diff, [], router)
      assert_receive {:llm_model, model}
      assert model == "openrouter/google/gemini-3-flash-preview"
    end
  end

  describe "route/3 with routing disabled" do
    setup do
      config_name = start_config!()

      # LLM that should never be called
      spy_llm = fn _params -> raise "LLM should not be called when routing disabled" end

      router_name = start_router!(config_name, spy_llm)

      # Patch config to disable routing
      :sys.replace_state(config_name, fn state ->
        Map.update!(state, :routing, &Map.put(&1, :enabled, false))
      end)

      %{router: router_name}
    end

    test "skips LLM and uses fallback when routing disabled", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == false
      assert length(result.panel) == 3
      assert "trace" in result.panel
      assert result.planner_trace.fallback.reason == "routing_disabled"
    end
  end

  describe "route/3 when LLM raises" do
    setup do
      config_name = start_config!()

      # LLM that raises an exception
      raising_llm = fn _params -> raise RuntimeError, "connection timeout" end

      router_name = start_router!(config_name, raising_llm)

      %{router: router_name}
    end

    test "catches exception and falls back gracefully", %{router: router} do
      {:ok, result} = Router.route(@simple_diff, [], router)
      assert result.routing_used == false
      assert length(result.panel) == 3
      assert result.planner_trace.fallback.reason == "llm_exception"
    end
  end

  describe "bench-aware planning" do
    test "active bench overrides constrain eligibility and selection" do
      config_name =
        start_config!(%{
          reviewers: %{
            atlas: %{enabled: false},
            craft: %{enabled: false},
            fuse: %{enabled: false}
          },
          routing: %{
            fallback_panel: ["trace", "guard", "proof"],
            always_include: ["trace"],
            include_if_code_changed: ["guard"]
          }
        })

      router = start_router!(config_name, fn _params -> {:error, :api_unavailable} end)

      {:ok, result} = Router.route(@simple_diff, [], router)

      assert result.planner_trace.eligible_bench == ["trace", "guard", "proof"]
      assert result.panel == ["trace", "guard", "proof"]
      refute Enum.any?(["atlas", "craft", "fuse"], &(&1 in result.panel))
    end

    test "provider, model, prompt, and template overrides preserve routing selection" do
      default_config = start_config!()

      override_config =
        start_config!(%{
          providers: %{
            deterministic: %{adapter: "deterministic"}
          },
          models: %{
            deterministic_review: %{
              provider: "deterministic",
              name: "deterministic/review-pass"
            }
          },
          prompts: %{
            alt_correctness: %{content: "ALT correctness prompt"}
          },
          templates: %{
            alt_review: %{content: "ALT template for {{PERSPECTIVE}}"}
          },
          reviewers: %{
            trace: %{
              model: "deterministic_review",
              prompt: "alt_correctness",
              template: "alt_review"
            }
          }
        })

      default_router = start_router!(default_config, fn _params -> {:error, :api_unavailable} end)

      override_router =
        start_router!(override_config, fn _params -> {:error, :api_unavailable} end)

      {:ok, default_result} = Router.route(@simple_diff, [], default_router)
      {:ok, override_result} = Router.route(@simple_diff, [], override_router)

      assert override_result.panel == default_result.panel
      assert override_result.model_tier == default_result.model_tier

      assert override_result.planner_trace.selected_team ==
               default_result.planner_trace.selected_team

      assert override_result.planner_trace.eligible_bench ==
               default_result.planner_trace.eligible_bench
    end

    test "repository context changes routing for the same patch shape" do
      plain_repo =
        create_repo_fixture!(%{
          "lib/service.ex" => "defmodule Service do\nend\n"
        })

      public_repo =
        create_repo_fixture!(%{
          "lib/service.ex" => "defmodule Service do\nend\n",
          "priv/openapi/openapi.yaml" => "openapi: 3.0.0\ninfo:\n  title: Billing\n"
        })

      config_name = start_config!()
      router = start_router!(config_name, fn _params -> {:error, :api_unavailable} end)

      on_exit(fn ->
        File.rm_rf(plain_repo)
        File.rm_rf(public_repo)
      end)

      {:ok, plain_result} =
        Router.route(@repo_aware_diff, [metadata: %{repo: plain_repo}], router)

      {:ok, public_result} =
        Router.route(@repo_aware_diff, [metadata: %{repo: public_repo}], router)

      assert plain_result.panel != public_result.panel or
               plain_result.model_tier != public_result.model_tier

      assert plain_result.planner_trace.repo_context.signals.public_contract_surface == false
      assert public_result.planner_trace.repo_context.signals.public_contract_surface == true
    end

    test "docs-only changes stay minimal in public-contract repositories" do
      public_repo =
        create_repo_fixture!(%{
          "priv/openapi/openapi.yaml" => "openapi: 3.0.0\ninfo:\n  title: Billing\n"
        })

      config_name = start_config!()
      router = start_router!(config_name, fn _params -> {:error, :api_unavailable} end)

      on_exit(fn ->
        File.rm_rf(public_repo)
      end)

      {:ok, result} = Router.route(@doc_only_diff, [metadata: %{repo: public_repo}], router)

      assert result.model_tier == :flash
      assert result.panel == ["trace"]
      assert result.planner_trace.repo_context.signals.public_contract_surface == true
      assert result.planner_trace.diff_classification.doc_only == true
      assert result.planner_trace.required_reviewers == ["trace"]
    end

    test "test-only changes stay minimal in security-sensitive repositories" do
      security_repo =
        create_repo_fixture!(%{
          "lib/app/auth/policy.ex" => "defmodule App.Auth.Policy do\nend\n"
        })

      config_name = start_config!()
      router = start_router!(config_name, fn _params -> {:error, :api_unavailable} end)

      on_exit(fn ->
        File.rm_rf(security_repo)
      end)

      {:ok, result} = Router.route(@test_only_diff, [metadata: %{repo: security_repo}], router)

      assert result.model_tier == :flash
      assert result.panel == ["trace", "proof"]
      assert result.planner_trace.repo_context.signals.security_sensitive_repo == true
      assert result.planner_trace.diff_classification.test_only == true
      assert result.planner_trace.required_reviewers == ["trace"]
    end

    test "routing config can explicitly broaden docs-only coverage in repo-sensitive repos" do
      public_repo =
        create_repo_fixture!(%{
          "priv/openapi/openapi.yaml" => "openapi: 3.0.0\ninfo:\n  title: Billing\n"
        })

      config_name =
        start_config!(%{
          routing: %{
            always_include: ["trace", "guard", "proof"]
          }
        })

      router = start_router!(config_name, fn _params -> {:error, :api_unavailable} end)

      on_exit(fn ->
        File.rm_rf(public_repo)
      end)

      {:ok, result} = Router.route(@doc_only_diff, [metadata: %{repo: public_repo}], router)

      assert result.model_tier == :flash
      assert result.panel == ["trace", "guard", "proof"]
      assert result.planner_trace.repo_context.signals.public_contract_surface == true
      assert result.planner_trace.required_reviewers == ["trace", "guard", "proof"]
    end

    test "risky changes escalate to higher-risk coverage" do
      config_name = start_config!()
      router = start_router!(config_name, fn _params -> {:error, :api_unavailable} end)

      {:ok, ordinary} = Router.route(@simple_diff, [], router)
      {:ok, risky} = Router.route(@security_diff, [], router)

      assert risky.model_tier == :pro
      assert length(risky.panel) >= length(ordinary.panel)
      assert risky.planner_trace.diff_classification.risky_change == true
      assert "guard" in risky.panel
      assert risky.panel != ordinary.panel
    end

    test "broad multi-surface changes widen the selected panel" do
      config_name = start_config!()
      router = start_router!(config_name, fn _params -> {:error, :api_unavailable} end)

      {:ok, narrow} = Router.route(@narrow_diff, [], router)
      {:ok, broad} = Router.route(@broad_diff, [], router)

      assert narrow.planner_trace.diff_classification.broad_change == false
      assert broad.planner_trace.diff_classification.broad_change == true
      assert length(broad.panel) > length(narrow.panel)
    end

    test "deterministic fallback is replayable under the same doubles" do
      config_name = start_config!()
      router = start_router!(config_name, fn _params -> {:ok, ["trace"]} end)

      {:ok, first} = Router.route(@simple_diff, [], router)
      {:ok, second} = Router.route(@simple_diff, [], router)

      assert first.panel == second.panel
      assert first.model_tier == second.model_tier
      assert first.planner_trace == second.planner_trace
    end
  end
end
