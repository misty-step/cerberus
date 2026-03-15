defmodule Cerberus.Store do
  @moduledoc false

  use GenServer

  @schema_statements [
    """
    CREATE TABLE IF NOT EXISTS review_runs (
      id INTEGER PRIMARY KEY,
      repo TEXT,
      pr_number INTEGER,
      head_sha TEXT,
      status TEXT NOT NULL DEFAULT 'queued',
      aggregated_verdict_json TEXT,
      completed_at TEXT,
      inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS verdicts (
      id INTEGER PRIMARY KEY,
      review_run_id INTEGER NOT NULL,
      reviewer TEXT NOT NULL,
      verdict TEXT NOT NULL,
      inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY,
      review_run_id INTEGER,
      kind TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS review_costs (
      id INTEGER PRIMARY KEY,
      review_run_id INTEGER,
      reviewer TEXT NOT NULL,
      model TEXT NOT NULL,
      prompt_tokens INTEGER NOT NULL DEFAULT 0,
      completion_tokens INTEGER NOT NULL DEFAULT 0,
      cost_usd REAL NOT NULL DEFAULT 0.0,
      duration_ms INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'success',
      is_fallback INTEGER NOT NULL DEFAULT 0,
      inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
  ]

  def start_link(opts) do
    {name, opts} = Keyword.pop(opts, :name)

    if name do
      GenServer.start_link(__MODULE__, opts, name: name)
    else
      GenServer.start_link(__MODULE__, opts)
    end
  end

  @spec ensure_schema(pid() | atom()) :: :ok | {:error, term()}
  def ensure_schema(store) do
    GenServer.call(store, :ensure_schema)
  end

  @spec table_names(pid() | atom()) :: {:ok, [String.t()]} | {:error, term()}
  def table_names(store) do
    GenServer.call(store, :table_names)
  end

  @spec create_review_run(pid() | atom(), map()) :: integer()
  def create_review_run(store, attrs) do
    GenServer.call(store, {:create_review_run, attrs})
  end

  @spec get_review_run(pid() | atom(), integer()) :: {:ok, map()} | {:error, :not_found}
  def get_review_run(store, id) do
    GenServer.call(store, {:get_review_run, id})
  end

  @spec update_review_run(pid() | atom(), integer(), map()) :: :ok | {:error, term()}
  def update_review_run(store, id, attrs) do
    GenServer.call(store, {:update_review_run, id, attrs})
  end

  @doc """
  Insert a cost record for a reviewer execution.

  Attrs: `:review_run_id`, `:reviewer`, `:model`, `:prompt_tokens`,
  `:completion_tokens`, `:cost_usd`, `:duration_ms`, `:status`, `:is_fallback`.
  """
  @spec insert_cost(pid() | atom(), map()) :: :ok | {:error, term()}
  def insert_cost(store, attrs) do
    GenServer.call(store, {:insert_cost, attrs})
  end

  @doc """
  Query model performance metrics grouped by model.

  Returns a list of maps with: `model`, `total_reviews`, `successes`,
  `success_rate`, `avg_latency_ms`, `fallback_rate`, `total_cost_usd`,
  `total_prompt_tokens`, `total_completion_tokens`.
  """
  @spec model_performance(pid() | atom()) :: {:ok, [map()]} | {:error, term()}
  def model_performance(store) do
    GenServer.call(store, :model_performance)
  end

  @doc """
  Query cost breakdown for a specific review run.

  Returns a list of per-reviewer cost records.
  """
  @spec review_run_costs(pid() | atom(), integer()) :: {:ok, [map()]} | {:error, term()}
  def review_run_costs(store, review_run_id) do
    GenServer.call(store, {:review_run_costs, review_run_id})
  end

  @impl true
  def init(opts) do
    database_path = Keyword.get(opts, :database_path, Cerberus.database_path())

    with :ok <- ensure_database_directory(database_path),
         {:ok, conn} <- Exqlite.Sqlite3.open(database_path),
         :ok <- configure_pragmas(conn),
         :ok <- ensure_schema_tables(conn) do
      state = %{conn: conn, database_path: database_path}
      {:ok, state}
    end
  end

  @impl true
  def handle_call(:ensure_schema, _from, %{conn: conn} = state) do
    {:reply, ensure_schema_tables(conn), state}
  end

  def handle_call(:table_names, _from, %{conn: conn} = state) do
    result =
      with {:ok, statement} <-
             Exqlite.Sqlite3.prepare(
               conn,
               "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
             ) do
        rows = collect_rows(conn, statement, [])
        Exqlite.Sqlite3.release(conn, statement)
        rows
      end

    {:reply, result, state}
  end

  def handle_call({:create_review_run, attrs}, _from, %{conn: conn} = state) do
    sql = """
    INSERT INTO review_runs (repo, pr_number, head_sha, status)
    VALUES (?1, ?2, ?3, 'queued')
    """

    result =
      with {:ok, stmt} <- Exqlite.Sqlite3.prepare(conn, sql) do
        try do
          with :ok <- Exqlite.Sqlite3.bind(stmt, [attrs[:repo], attrs[:pr_number], attrs[:head_sha]]),
               :done <- Exqlite.Sqlite3.step(conn, stmt) do
            Exqlite.Sqlite3.last_insert_rowid(conn)
          else
            {:error, _} = err -> err
            other -> {:error, other}
          end
        after
          Exqlite.Sqlite3.release(conn, stmt)
        end
      end

    id =
      case result do
        {:ok, rowid} -> rowid
        rowid when is_integer(rowid) -> rowid
        {:error, _} = err -> err
      end

    {:reply, id, state}
  end

  def handle_call({:get_review_run, id}, _from, %{conn: conn} = state) do
    sql = """
    SELECT id, repo, pr_number, head_sha, status, aggregated_verdict_json, completed_at, inserted_at
    FROM review_runs WHERE id = ?1
    """

    result =
      with {:ok, stmt} <- Exqlite.Sqlite3.prepare(conn, sql) do
        try do
          with :ok <- Exqlite.Sqlite3.bind(stmt, [id]) do
            case Exqlite.Sqlite3.step(conn, stmt) do
              {:row, [id, repo, pr, sha, status, verdict_json, completed, inserted]} ->
                {:ok, %{
                  review_id: id,
                  repo: repo,
                  pr_number: pr,
                  head_sha: sha,
                  status: status,
                  aggregated_verdict: safe_decode(verdict_json),
                  completed_at: completed,
                  inserted_at: inserted
                }}

              :done ->
                {:error, :not_found}
            end
          end
        after
          Exqlite.Sqlite3.release(conn, stmt)
        end
      end

    {:reply, result, state}
  end

  def handle_call({:update_review_run, id, attrs}, _from, %{conn: conn} = state) do
    sets = []
    bindings = []
    idx = 1

    {sets, bindings, idx} =
      Enum.reduce([:status, :aggregated_verdict_json, :completed_at], {sets, bindings, idx}, fn key, {s, b, i} ->
        case Map.get(attrs, key) do
          nil -> {s, b, i}
          val -> {["#{key} = ?#{i}" | s], b ++ [val], i + 1}
        end
      end)

    if sets == [] do
      {:reply, :ok, state}
    else
      sql = "UPDATE review_runs SET #{Enum.reverse(sets) |> Enum.join(", ")} WHERE id = ?#{idx}"

      result =
        with {:ok, stmt} <- Exqlite.Sqlite3.prepare(conn, sql) do
          try do
            with :ok <- Exqlite.Sqlite3.bind(stmt, bindings ++ [id]),
                 :done <- Exqlite.Sqlite3.step(conn, stmt) do
              :ok
            else
              {:error, _} = err -> err
              other -> {:error, other}
            end
          after
            Exqlite.Sqlite3.release(conn, stmt)
          end
        end

      {:reply, result, state}
    end
  end

  def handle_call({:insert_cost, attrs}, _from, %{conn: conn} = state) do
    sql = """
    INSERT INTO review_costs
      (review_run_id, reviewer, model, prompt_tokens, completion_tokens,
       cost_usd, duration_ms, status, is_fallback)
    VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
    """

    result =
      with {:ok, stmt} <- Exqlite.Sqlite3.prepare(conn, sql) do
        try do
          with :ok <-
                 Exqlite.Sqlite3.bind(stmt, [
                   attrs[:review_run_id],
                   attrs[:reviewer] || "",
                   attrs[:model] || "",
                   attrs[:prompt_tokens] || 0,
                   attrs[:completion_tokens] || 0,
                   attrs[:cost_usd] || 0.0,
                   attrs[:duration_ms] || 0,
                   to_string(attrs[:status] || "success"),
                   if(attrs[:is_fallback], do: 1, else: 0)
                 ]),
               :done <- Exqlite.Sqlite3.step(conn, stmt) do
            :ok
          else
            {:error, _} = err -> err
            other -> {:error, other}
          end
        after
          Exqlite.Sqlite3.release(conn, stmt)
        end
      end

    {:reply, result, state}
  end

  def handle_call(:model_performance, _from, %{conn: conn} = state) do
    sql = """
    SELECT
      model,
      COUNT(*) as total_reviews,
      SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes,
      CAST(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS REAL) / COUNT(*) as success_rate,
      AVG(duration_ms) as avg_latency_ms,
      CAST(SUM(is_fallback) AS REAL) / COUNT(*) as fallback_rate,
      SUM(cost_usd) as total_cost_usd,
      SUM(prompt_tokens) as total_prompt_tokens,
      SUM(completion_tokens) as total_completion_tokens
    FROM review_costs
    GROUP BY model
    ORDER BY total_reviews DESC
    """

    result = query_rows(conn, sql, [], &parse_model_performance_row/1)
    {:reply, result, state}
  end

  def handle_call({:review_run_costs, run_id}, _from, %{conn: conn} = state) do
    sql = """
    SELECT reviewer, model, prompt_tokens, completion_tokens,
           cost_usd, duration_ms, status, is_fallback
    FROM review_costs
    WHERE review_run_id = ?1
    ORDER BY inserted_at
    """

    result = query_rows(conn, sql, [run_id], &parse_cost_row/1)
    {:reply, result, state}
  end

  @impl true
  def terminate(_reason, %{conn: conn}) do
    Exqlite.Sqlite3.close(conn)
    :ok
  end

  defp configure_pragmas(conn) do
    Enum.reduce_while(
      ["PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=5000", "PRAGMA foreign_keys=ON"],
      :ok,
      fn pragma, :ok ->
        case Exqlite.Sqlite3.execute(conn, pragma) do
          :ok -> {:cont, :ok}
          {:error, reason} -> {:halt, {:error, reason}}
        end
      end
    )
  end

  defp ensure_database_directory(database_path) do
    database_path
    |> Path.dirname()
    |> File.mkdir_p()
  end

  defp ensure_schema_tables(conn) do
    Enum.reduce_while(@schema_statements, :ok, fn statement, :ok ->
      case Exqlite.Sqlite3.execute(conn, statement) do
        :ok -> {:cont, :ok}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  defp collect_rows(conn, statement, acc) do
    case Exqlite.Sqlite3.step(conn, statement) do
      {:row, [name]} -> collect_rows(conn, statement, [name | acc])
      :done -> {:ok, Enum.reverse(acc)}
      {:error, reason} -> {:error, reason}
    end
  end

  defp query_rows(conn, sql, bindings, row_parser) do
    with {:ok, stmt} <- Exqlite.Sqlite3.prepare(conn, sql) do
      try do
        with :ok <- bind_if_needed(conn, stmt, bindings) do
          collect_parsed_rows(conn, stmt, row_parser, [])
        end
      after
        Exqlite.Sqlite3.release(conn, stmt)
      end
    end
  end

  defp bind_if_needed(_conn, _stmt, []), do: :ok
  defp bind_if_needed(_conn, stmt, bindings), do: Exqlite.Sqlite3.bind(stmt, bindings)

  defp collect_parsed_rows(conn, stmt, parser, acc) do
    case Exqlite.Sqlite3.step(conn, stmt) do
      {:row, values} -> collect_parsed_rows(conn, stmt, parser, [parser.(values) | acc])
      :done -> {:ok, Enum.reverse(acc)}
      {:error, reason} -> {:error, reason}
    end
  end

  defp parse_model_performance_row([
         model,
         total,
         successes,
         success_rate,
         avg_latency,
         fallback_rate,
         total_cost,
         prompt_tokens,
         completion_tokens
       ]) do
    %{
      model: model,
      total_reviews: total,
      successes: successes,
      success_rate: success_rate || 0.0,
      avg_latency_ms: avg_latency || 0.0,
      fallback_rate: fallback_rate || 0.0,
      total_cost_usd: total_cost || 0.0,
      total_prompt_tokens: prompt_tokens || 0,
      total_completion_tokens: completion_tokens || 0
    }
  end

  defp safe_decode(nil), do: nil
  defp safe_decode(json) when is_binary(json) do
    case Jason.decode(json) do
      {:ok, val} -> val
      _ -> nil
    end
  end

  defp parse_cost_row([reviewer, model, prompt_tokens, completion_tokens,
                       cost_usd, duration_ms, status, is_fallback]) do
    %{
      reviewer: reviewer,
      model: model,
      prompt_tokens: prompt_tokens,
      completion_tokens: completion_tokens,
      cost_usd: cost_usd,
      duration_ms: duration_ms,
      status: status,
      is_fallback: is_fallback == 1
    }
  end
end
