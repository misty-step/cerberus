defmodule Cerberus.ConfigTest do
  use ExUnit.Case, async: true

  alias Cerberus.Config
  alias Cerberus.Config.Persona

  @repo_root Path.expand("../../..", __DIR__)

  setup do
    name = unique_name("config")
    {:ok, pid} = Config.start_link(repo_root: @repo_root, name: name)
    %{server: name, pid: pid}
  end

  defp unique_name(prefix), do: :"#{prefix}_#{System.unique_integer([:positive])}"

  defp start_config!(overrides) do
    name = unique_name("config_override")
    {:ok, pid} = Config.start_link(repo_root: @repo_root, name: name, config_overrides: overrides)
    %{server: name, pid: pid}
  end

  describe "personas/1" do
    test "returns all six personas with required fields", %{server: server} do
      personas = Config.personas(server)

      assert length(personas) == 6

      for p <- personas do
        assert %Persona{} = p
        assert is_binary(p.name) and p.name != ""
        assert is_atom(p.perspective)
        assert is_binary(p.prompt) and p.prompt != ""
        assert p.model_policy == :pool or is_binary(p.model_policy)
      end
    end

    test "includes all expected reviewer names", %{server: server} do
      names = Config.personas(server) |> Enum.map(& &1.name) |> Enum.sort()
      assert names == ~w(atlas craft fuse guard proof trace)
    end

    test "maps perspectives correctly", %{server: server} do
      by_name =
        Config.personas(server)
        |> Map.new(&{&1.name, &1})

      assert by_name["trace"].perspective == :correctness
      assert by_name["guard"].perspective == :security
      assert by_name["proof"].perspective == :testing
      assert by_name["atlas"].perspective == :architecture
      assert by_name["fuse"].perspective == :resilience
      assert by_name["craft"].perspective == :maintainability
    end

    test "loads prompt content from perspective files", %{server: server} do
      trace = Config.personas(server) |> Enum.find(&(&1.name == "trace"))
      assert String.contains?(trace.prompt, "correctness")
    end
  end

  describe "model_pool/2" do
    test "returns a list of model strings for each tier", %{server: server} do
      for tier <- [:wave1, :wave2, :wave3] do
        pool = Config.model_pool(tier, server)
        assert is_list(pool)
        assert length(pool) > 0
        assert Enum.all?(pool, &is_binary/1)
      end
    end

    test "wave1 contains flash-tier models", %{server: server} do
      pool = Config.model_pool(:wave1, server)
      assert Enum.any?(pool, &String.contains?(&1, "openrouter/"))
    end

    test "returns deterministic configured order", %{server: server} do
      assert Config.model_pool(:wave1, server) == [
               "openrouter/x-ai/grok-4.1-fast",
               "openrouter/inception/mercury-2",
               "openrouter/minimax/minimax-m2.5"
             ]
    end

    test "returns empty list for unknown tier", %{server: server} do
      assert Config.model_pool(:nonexistent, server) == []
    end
  end

  describe "verdict_rules/1" do
    test "returns fail_on, warn_on, and confidence_min", %{server: server} do
      rules = Config.verdict_rules(server)

      assert is_binary(rules.fail_on)
      assert is_binary(rules.warn_on)
      assert is_float(rules.confidence_min) or is_integer(rules.confidence_min)
    end

    test "confidence_min matches config default", %{server: server} do
      rules = Config.verdict_rules(server)
      assert rules.confidence_min == 0.7
    end

    test "fail_on matches config default", %{server: server} do
      rules = Config.verdict_rules(server)
      assert rules.fail_on == "any_critical_or_2_major"
    end
  end

  describe "routing/1" do
    test "returns panel_size, always_include, and fallback_panel", %{server: server} do
      routing = Config.routing(server)

      assert is_integer(routing.panel_size)
      assert is_list(routing.always_include)
      assert is_list(routing.fallback_panel)
    end

    test "panel_size matches config default", %{server: server} do
      routing = Config.routing(server)
      assert routing.panel_size == 4
    end

    test "always_include contains trace", %{server: server} do
      routing = Config.routing(server)
      assert "trace" in routing.always_include
    end

    test "fallback_panel contains all six reviewers", %{server: server} do
      routing = Config.routing(server)
      assert Enum.sort(routing.fallback_panel) == ~w(atlas craft fuse guard proof trace)
    end

    test "includes routing model from config", %{server: server} do
      routing = Config.routing(server)
      assert is_binary(routing.model)
      assert String.contains?(routing.model, "openrouter/")
    end

    test "includes enabled flag", %{server: server} do
      routing = Config.routing(server)
      assert routing.enabled == true
    end
  end

  describe "resolved_snapshot/2" do
    test "returns deterministic redacted snapshot for the active reviewer bench", %{
      server: server
    } do
      snapshot = Config.resolved_snapshot(server, model_tier: :standard)

      assert snapshot.model_tier == "standard"
      assert snapshot.planner_model.id == "gemini_3_flash_preview"
      assert snapshot.planner_model.provider.source == "default"

      trace = Enum.find(snapshot.reviewers, &(&1.id == "trace"))
      assert trace.perspective.value == "correctness"
      assert trace.provider.value == "openrouter"
      assert trace.model.id == "kimi_k2_5"
      assert trace.prompt.path == "pi/agents/correctness.md"
      assert trace.template.path == "templates/review-prompt.md"
      assert String.starts_with?(trace.prompt.digest, "sha256:")
      assert String.starts_with?(trace.template.digest, "sha256:")
      refute Map.has_key?(trace.prompt, :content)
      refute Map.has_key?(trace.template, :content)
    end

    test "applies partial overrides while preserving inherited defaults" do
      %{server: server} =
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
              prompt: "alt_correctness",
              template: "alt_review",
              model: "deterministic_review",
              description: "Trace override"
            },
            sentinel: %{
              perspective: "security",
              prompt: "security",
              template: "review",
              model: "deterministic_review",
              description: "Sentinel override",
              override: "maintainers_only",
              tools: %{shell: false}
            }
          },
          routing: %{
            fallback_panel: ["trace", "sentinel", "guard", "atlas"]
          }
        })

      personas = Config.personas(server)
      snapshot = Config.resolved_snapshot(server, model_tier: :standard)

      assert Enum.map(personas, & &1.id) |> Enum.sort() ==
               ~w(atlas craft fuse guard proof sentinel trace)

      trace = Enum.find(snapshot.reviewers, &(&1.id == "trace"))
      atlas = Enum.find(snapshot.reviewers, &(&1.id == "atlas"))
      sentinel = Enum.find(snapshot.reviewers, &(&1.id == "sentinel"))

      assert trace.provider.value == "deterministic"
      assert trace.provider.source == "override"
      assert trace.model.id == "deterministic_review"
      assert trace.prompt.id == "alt_correctness"
      assert trace.template.id == "alt_review"
      assert atlas.prompt.id == "architecture"
      assert atlas.prompt.source == "default"
      assert sentinel.perspective.value == "security"
      assert sentinel.model.id == "deterministic_review"

      assert Config.routing(server).fallback_panel == ["trace", "sentinel", "guard", "atlas"]
    end
  end

  describe "config validation" do
    test "rejects duplicate reviewer ids in overrides" do
      name = unique_name("config_duplicate")
      Process.flag(:trap_exit, true)

      assert {:error, {:invalid_config, diagnostics}} =
               Config.start_link(
                 repo_root: @repo_root,
                 name: name,
                 config_overrides: %{
                   reviewers: [
                     %{id: "trace", description: "first"},
                     %{id: "trace", description: "second"}
                   ]
                 }
               )

      assert Enum.any?(
               diagnostics,
               &(&1.path == "reviewers[1]" and &1.reason == "duplicate reviewer id")
             )
    end

    test "rejects invalid provider/model combinations, missing assets, unsupported keys, and wrong value types" do
      name = unique_name("config_invalid")
      Process.flag(:trap_exit, true)

      assert {:error, {:invalid_config, diagnostics}} =
               Config.start_link(
                 repo_root: @repo_root,
                 name: name,
                 config_overrides: %{
                   unsupported: true,
                   routing: %{panel_size: "four"},
                   providers: %{deterministic: %{adapter: "deterministic"}},
                   models: %{
                     bad_combo: %{
                       provider: "deterministic",
                       name: "openrouter/google/gemini-3-flash-preview"
                     }
                   },
                   prompts: %{
                     missing_prompt: %{path: "missing/prompt.md"}
                   },
                   reviewers: %{
                     trace: %{prompt: "missing_prompt", model: "bad_combo"}
                   }
                 }
               )

      paths = Map.new(diagnostics, &{&1.path, &1.reason})
      assert paths["overrides.unsupported"] == "unsupported override key"
      assert paths["routing.panel_size"] == "expected integer"
      assert paths["models.bad_combo"] == "invalid provider/model combination"
      assert paths["prompts.missing_prompt"] == "asset file not found"
    end

    test "rejects dangling reviewer references before planner work starts" do
      name = unique_name("config_dangling")
      Process.flag(:trap_exit, true)

      assert {:error, {:invalid_config, diagnostics}} =
               Config.start_link(
                 repo_root: @repo_root,
                 name: name,
                 config_overrides: %{
                   routing: %{always_include: ["ghost-reviewer"]}
                 }
               )

      assert Enum.any?(
               diagnostics,
               &(&1.path == "routing.always_include" and
                   &1.reason == "references unknown reviewer")
             )
    end
  end

  describe "reload/1" do
    test "reloads config and preserves valid state", %{server: server} do
      original = Config.personas(server) |> Enum.find(&(&1.name == "trace"))
      :ok = Config.reload(server)
      reloaded = Config.personas(server) |> Enum.find(&(&1.name == "trace"))
      assert reloaded.prompt == original.prompt
    end

    test "returns error and preserves state when config path is invalid", %{server: server} do
      original_personas = Config.personas(server)

      # Corrupt the repo_root in GenServer state to trigger reload failure
      :sys.replace_state(server, fn state ->
        Map.put(state, :repo_root, "/nonexistent/path")
      end)

      assert {:error, _reason} = Config.reload(server)

      # State preserved — personas unchanged
      assert Config.personas(server) == original_personas
    end
  end

  describe "automatic hot-reload" do
    test "detects prompt file modification and reloads", %{server: server, pid: pid} do
      original = Config.personas(server) |> Enum.find(&(&1.name == "trace"))
      prompt_path = Path.join([@repo_root, "pi", "agents", "correctness.md"])

      # Touch the file to update mtime
      File.touch!(prompt_path)

      # Trigger the poll manually and synchronize via a call (serialized after handle_info)
      send(pid, :check_prompts)
      Config.personas(server)

      reloaded = Config.personas(server) |> Enum.find(&(&1.name == "trace"))
      assert reloaded.prompt == original.prompt
    end
  end

  describe "init failure" do
    test "returns error when repo_root has no config" do
      name = :"config_bad_#{System.unique_integer([:positive])}"
      Process.flag(:trap_exit, true)

      assert {:error, _reason} =
               Config.start_link(repo_root: "/nonexistent/path", name: name)
    end
  end
end
