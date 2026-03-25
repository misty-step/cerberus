defmodule Cerberus.Config do
  @moduledoc """
  Resolved reviewer configuration registry for Cerberus.

  Loads one merged runtime configuration model from shipped defaults plus optional
  overrides, validates the full reviewer bench up-front, and exposes the
  resolved reviewer/routing data needed by planner and reviewer execution.
  """

  use GenServer

  alias Cerberus.Config.{Diagnostic, Loader, Persona}

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

  @spec resolve_panel([String.t()], atom(), GenServer.server()) ::
          {:ok, [map()]} | {:error, term()}
  def resolve_panel(panel_ids, model_tier, server \\ __MODULE__) do
    GenServer.call(server, {:resolve_panel, panel_ids, model_tier})
  end

  @spec resolved_snapshot(GenServer.server(), keyword()) :: map()
  def resolved_snapshot(server \\ __MODULE__, opts \\ []) do
    GenServer.call(server, {:resolved_snapshot, opts})
  end

  @spec format_diagnostics([Diagnostic.t()]) :: String.t()
  def format_diagnostics(diagnostics) when is_list(diagnostics) do
    diagnostics
    |> Enum.map(&Diagnostic.format/1)
    |> Enum.join("\n")
    |> then(fn body -> "Invalid Cerberus reviewer configuration:\n" <> body end)
  end

  @spec reload(GenServer.server()) :: :ok | {:error, term()}
  def reload(server \\ __MODULE__), do: GenServer.call(server, :reload)

  # --- Server Callbacks ---

  @impl true
  def init(opts) do
    repo_root = Keyword.get(opts, :repo_root, Cerberus.repo_root()) |> normalize_repo_root()
    overrides = Keyword.get(opts, :config_overrides, %{})

    case load_and_parse(repo_root, overrides) do
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
    ids = Map.get(state.model_pools, tier, [])
    pool = Enum.map(ids, &state.models[&1].name)
    {:reply, pool, state}
  end

  def handle_call(:verdict_rules, _from, state) do
    {:reply, state.verdict_rules, state}
  end

  def handle_call(:routing, _from, state) do
    {:reply, state.routing, state}
  end

  def handle_call({:resolve_panel, panel_ids, model_tier}, _from, state) do
    {:reply, Loader.resolve_panel(state, panel_ids, model_tier), state}
  end

  def handle_call({:resolved_snapshot, opts}, _from, state) do
    {:reply, Loader.resolved_snapshot(state, opts), state}
  end

  def handle_call(:reload, _from, state) do
    case load_and_parse(state.repo_root, state.overrides) do
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
    state = maybe_reload_assets(state)
    schedule_poll()
    {:noreply, state}
  end

  # --- Private ---

  defp schedule_poll do
    Process.send_after(self(), :check_prompts, @poll_interval_ms)
  end

  defp load_and_parse(repo_root, overrides) do
    Loader.load(repo_root, overrides)
  end

  defp maybe_reload_assets(state) do
    if assets_changed?(state.asset_mtimes) do
      case load_and_parse(state.repo_root, state.overrides) do
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

  defp assets_changed?(asset_mtimes) do
    Enum.any?(asset_mtimes, fn {path, mtime} ->
      case File.stat(path) do
        {:ok, stat} -> stat.mtime != mtime
        _ -> true
      end
    end)
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
