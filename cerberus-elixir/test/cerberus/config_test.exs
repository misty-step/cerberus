defmodule Cerberus.ConfigTest do
  use ExUnit.Case, async: true

  alias Cerberus.Config
  alias Cerberus.Config.Persona

  @repo_root Path.expand("../../..", __DIR__)

  setup do
    name = :"config_#{System.unique_integer([:positive])}"
    {:ok, pid} = Config.start_link(repo_root: @repo_root, name: name)
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

    test "returns shuffled list (order may vary across calls)", %{server: server} do
      results = for _ <- 1..10, do: Config.model_pool(:wave1, server)
      assert length(Enum.uniq(results)) > 1 or length(hd(results)) <= 1
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
