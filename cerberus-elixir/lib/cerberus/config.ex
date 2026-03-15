defmodule Cerberus.Config do
  @moduledoc """
  Typed config registry for Cerberus personas, model pools, verdict rules, and routing.

  Loads `defaults/config.yml` and `pi/agents/*.md` prompt files at boot.
  Polls prompt files for changes and hot-reloads on modification.

  ## Public API

      Cerberus.Config.personas()        # => [%Persona{}, ...]
      Cerberus.Config.model_pool(:wave1) # => ["openrouter/...", ...] (shuffled)
      Cerberus.Config.verdict_rules()    # => %{fail_on: ..., warn_on: ..., confidence_min: 0.7}
      Cerberus.Config.routing()          # => %{panel_size: 4, always_include: [...], ...}
      Cerberus.Config.reload()           # => :ok | {:error, reason}
  """

  use GenServer

  alias Cerberus.Config.Persona

  @poll_interval_ms 5_000

  # --- Client API ---

  def start_link(opts) do
    {name, opts} = Keyword.pop(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @spec personas(GenServer.server()) :: [Persona.t()]
  def personas(server \\ __MODULE__), do: GenServer.call(server, :personas)

  @spec model_pool(atom(), GenServer.server()) :: [String.t()]
  def model_pool(tier, server \\ __MODULE__), do: GenServer.call(server, {:model_pool, tier})

  @spec verdict_rules(GenServer.server()) :: map()
  def verdict_rules(server \\ __MODULE__), do: GenServer.call(server, :verdict_rules)

  @spec routing(GenServer.server()) :: map()
  def routing(server \\ __MODULE__), do: GenServer.call(server, :routing)

  @spec reload(GenServer.server()) :: :ok | {:error, term()}
  def reload(server \\ __MODULE__), do: GenServer.call(server, :reload)

  # --- Server Callbacks ---

  @impl true
  def init(opts) do
    repo_root = Keyword.get(opts, :repo_root, Cerberus.repo_root()) |> normalize_repo_root()

    case load_and_parse(repo_root) do
      {:ok, state} ->
        schedule_poll()
        {:ok, state}

      {:error, reason} ->
        {:stop, reason}
    end
  end

  @impl true
  def handle_call(:personas, _from, state) do
    {:reply, state.personas, state}
  end

  def handle_call({:model_pool, tier}, _from, state) do
    pool = Map.get(state.model_pools, tier, [])
    {:reply, Enum.shuffle(pool), state}
  end

  def handle_call(:verdict_rules, _from, state) do
    {:reply, state.verdict_rules, state}
  end

  def handle_call(:routing, _from, state) do
    {:reply, state.routing, state}
  end

  def handle_call(:reload, _from, state) do
    case load_and_parse(state.repo_root) do
      {:ok, new_state} ->
        {:reply, :ok, new_state}

      {:error, reason} ->
        require Logger
        Logger.warning("Config reload failed: #{inspect(reason)}, keeping current state")
        {:reply, {:error, reason}, state}
    end
  end

  @impl true
  def handle_info(:check_prompts, state) do
    state = maybe_reload_prompts(state)
    schedule_poll()
    {:noreply, state}
  end

  # --- Private ---

  defp schedule_poll do
    Process.send_after(self(), :check_prompts, @poll_interval_ms)
  end

  defp load_and_parse(repo_root) do
    config_path = Path.join(repo_root, "defaults/config.yml")

    with {:ok, raw} <- YamlElixir.read_from_file(config_path),
         {:ok, prompts, mtimes} <- load_prompts_with_mtimes(repo_root),
         {:ok, personas} <- build_personas(raw, prompts) do
      {:ok,
       %{
         repo_root: repo_root,
         personas: personas,
         model_pools: build_model_pools(raw),
         verdict_rules: build_verdict_rules(raw),
         routing: build_routing(raw),
         prompt_mtimes: mtimes
       }}
    end
  end

  defp build_personas(raw, prompts) do
    reviewers = Map.get(raw, "reviewers", [])

    Enum.reduce_while(reviewers, {:ok, []}, fn r, {:ok, acc} ->
      case Map.fetch(prompts, r["perspective"]) do
        {:ok, prompt} when byte_size(prompt) > 0 ->
          persona = %Persona{
            name: r["name"],
            perspective: String.to_atom(r["perspective"]),
            prompt: prompt,
            model_policy: parse_model_policy(r["model"]),
            description: r["description"],
            override: parse_atom(r["override"]),
            tools: r["tools"] || %{}
          }

          {:cont, {:ok, [persona | acc]}}

        {:ok, _empty} ->
          {:halt, {:error, {:empty_prompt, r["perspective"]}}}

        :error ->
          {:halt, {:error, {:missing_prompt, r["perspective"]}}}
      end
    end)
    |> case do
      {:ok, personas} -> {:ok, Enum.reverse(personas)}
      error -> error
    end
  end

  defp build_model_pools(raw) do
    raw
    |> get_in(["model", "wave_pools"])
    |> case do
      nil -> %{}
      pools -> Map.new(pools, fn {k, v} -> {String.to_atom(k), v} end)
    end
  end

  defp build_verdict_rules(raw) do
    verdict = Map.get(raw, "verdict", %{})

    %{
      fail_on: verdict["fail_on"] || "any_critical_or_2_major",
      warn_on: verdict["warn_on"] || "any_major_or_5_minor_or_3_minor_same_category",
      confidence_min: verdict["confidence_min"] || 0.7
    }
  end

  defp build_routing(raw) do
    routing = Map.get(raw, "routing", %{})

    %{
      panel_size: routing["panel_size"] || 4,
      always_include: routing["always_include"] || [],
      fallback_panel: routing["fallback_panel"] || [],
      include_if_code_changed: routing["include_if_code_changed"] || []
    }
  end

  defp parse_model_policy("pool"), do: :pool
  defp parse_model_policy(model) when is_binary(model), do: model
  defp parse_model_policy(_), do: :pool

  defp parse_atom(nil), do: nil
  defp parse_atom(s) when is_binary(s), do: String.to_atom(s)
  defp parse_atom(a) when is_atom(a), do: a

  defp load_prompts_with_mtimes(repo_root) do
    glob = Application.get_env(:cerberus_elixir, :prompt_glob, "pi/agents/*.md")

    paths =
      repo_root
      |> Path.join(glob)
      |> Path.wildcard()
      |> Enum.sort()

    result =
      Enum.reduce_while(paths, {:ok, %{}, %{}}, fn path, {:ok, prompts, mtimes} ->
        with {:ok, content} <- File.read(path),
             {:ok, stat} <- File.stat(path) do
          key = Path.basename(path, ".md")
          {:cont, {:ok, Map.put(prompts, key, content), Map.put(mtimes, path, stat.mtime)}}
        else
          {:error, reason} -> {:halt, {:error, {:prompt_read_failed, path, reason}}}
        end
      end)

    case result do
      {:ok, prompts, _mtimes} when map_size(prompts) == 0 -> {:error, :no_prompts_found}
      {:ok, prompts, mtimes} -> {:ok, prompts, mtimes}
      error -> error
    end
  end

  defp maybe_reload_prompts(state) do
    glob = Application.get_env(:cerberus_elixir, :prompt_glob, "pi/agents/*.md")

    current_paths =
      state.repo_root
      |> Path.join(glob)
      |> Path.wildcard()
      |> MapSet.new()

    known_paths = state.prompt_mtimes |> Map.keys() |> MapSet.new()

    # Detect new or removed files
    files_changed = current_paths != known_paths

    # Detect mtime changes on known files
    mtimes_changed =
      not files_changed and
        Enum.any?(Map.keys(state.prompt_mtimes), fn path ->
          case File.stat(path) do
            {:ok, stat} -> stat.mtime != state.prompt_mtimes[path]
            _ -> true
          end
        end)

    if files_changed or mtimes_changed do
      case load_and_parse(state.repo_root) do
        {:ok, new_state} ->
          new_state

        {:error, reason} ->
          require Logger
          Logger.warning("Config hot-reload failed: #{inspect(reason)}, keeping current state")
          state
      end
    else
      state
    end
  end

  defp normalize_repo_root(candidate) do
    if File.exists?(Path.join(candidate, "defaults/config.yml")) do
      candidate
    else
      parent = Path.expand("..", candidate)

      if File.exists?(Path.join(parent, "defaults/config.yml")) do
        parent
      else
        candidate
      end
    end
  end
end
