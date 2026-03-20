defmodule Cerberus.Store do
  @moduledoc false

  use GenServer
  require Logger

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
      perspective TEXT NOT NULL DEFAULT '',
      confidence REAL NOT NULL DEFAULT 0.0,
      summary TEXT NOT NULL DEFAULT '',
      findings_json TEXT NOT NULL DEFAULT '[]',
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

  @verdicts_column_migrations [
    {"perspective", "ALTER TABLE verdicts ADD COLUMN perspective TEXT NOT NULL DEFAULT ''"},
    {"confidence", "ALTER TABLE verdicts ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0"},
    {"summary", "ALTER TABLE verdicts ADD COLUMN summary TEXT NOT NULL DEFAULT ''"},
    {"findings_json", "ALTER TABLE verdicts ADD COLUMN findings_json TEXT NOT NULL DEFAULT '[]'"}
  ]
  @known_tables ~w(events review_costs review_runs verdicts)

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

  @spec create_review_run(pid() | atom(), map()) :: non_neg_integer() | {:error, term()}
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
  Insert a reviewer verdict record for a review run.

  Attrs: `:review_run_id`, `:reviewer`, `:perspective`, `:verdict`,
  `:confidence`, `:summary`, `:findings`.
  """
  @spec insert_verdict(pid() | atom(), map()) :: :ok | {:error, term()}
  def insert_verdict(store, attrs) do
    GenServer.call(store, {:insert_verdict, attrs})
  end

  @doc """
  Insert reviewer verdict records for a review run atomically.

  If any verdict payload is invalid, none of the rows are written.
  """
  @spec insert_verdicts(pid() | atom(), [map()]) :: :ok | {:error, term()}
  def insert_verdicts(store, attrs_list) do
    GenServer.call(store, {:insert_verdicts, attrs_list})
  end

  @doc """
  Query persisted reviewer verdicts for a specific review run.

  Returns a list of per-reviewer verdict records in insertion order.
  """
  @spec review_run_verdicts(pid() | atom(), integer()) :: {:ok, [map()]} | {:error, term()}
  def review_run_verdicts(store, review_run_id) do
    GenServer.call(store, {:review_run_verdicts, review_run_id})
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
  Insert reviewer cost records for a review run atomically.

  If any row fails to write, none of the rows are committed.
  """
  @spec insert_costs(pid() | atom(), [map()]) :: :ok | {:error, term()}
  def insert_costs(store, attrs_list) do
    GenServer.call(store, {:insert_costs, attrs_list})
  end

  @doc "Insert an event record (errors, lifecycle transitions)."
  @spec insert_event(pid() | atom(), map()) :: :ok | {:error, term()}
  def insert_event(store, attrs) do
    GenServer.call(store, {:insert_event, attrs})
  end

  @doc "List events for a review run."
  @spec list_events(pid() | atom(), integer()) :: {:ok, [map()]} | {:error, term()}
  def list_events(store, review_run_id) do
    GenServer.call(store, {:list_events, review_run_id})
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
         :ok <- ensure_schema_ready(conn) do
      state = %{conn: conn, database_path: database_path}
      {:ok, state}
    end
  end

  @impl true
  def handle_call(:ensure_schema, _from, %{conn: conn} = state) do
    {:reply, ensure_schema_ready(conn), state}
  end

  def handle_call(:table_names, _from, %{conn: conn} = state) do
    sql = "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"

    result =
      with_statement(conn, sql, [], fn _conn, stmt ->
        collect_rows(conn, stmt, [])
      end)

    {:reply, result, state}
  end

  def handle_call({:create_review_run, attrs}, _from, %{conn: conn} = state) do
    sql =
      "INSERT INTO review_runs (repo, pr_number, head_sha, status) VALUES (?1, ?2, ?3, 'queued')"

    bindings = [attrs[:repo], attrs[:pr_number], attrs[:head_sha]]

    result =
      exec(conn, sql, bindings, fn conn, _stmt ->
        case Exqlite.Sqlite3.last_insert_rowid(conn) do
          {:ok, rowid} -> rowid
          rowid when is_integer(rowid) -> rowid
        end
      end)

    {:reply, result, state}
  end

  def handle_call({:get_review_run, id}, _from, %{conn: conn} = state) do
    sql = """
    SELECT id, repo, pr_number, head_sha, status, aggregated_verdict_json, completed_at, inserted_at
    FROM review_runs WHERE id = ?1
    """

    result =
      with_statement(conn, sql, [id], fn conn, stmt ->
        case Exqlite.Sqlite3.step(conn, stmt) do
          {:row, [id, repo, pr, sha, status, verdict_json, completed, inserted]} ->
            {:ok,
             %{
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
      end)

    {:reply, result, state}
  end

  def handle_call({:update_review_run, id, attrs}, _from, %{conn: conn} = state) do
    {sets, bindings, idx} =
      Enum.reduce([:status, :aggregated_verdict_json, :completed_at], {[], [], 1}, fn key,
                                                                                      {s, b, i} ->
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
        exec(conn, sql, bindings ++ [id], fn conn, _stmt ->
          changes_count(conn)
        end)

      result =
        case result do
          {:ok, 0} -> {:error, :not_found}
          {:ok, _n} -> :ok
          other -> other
        end

      {:reply, result, state}
    end
  end

  def handle_call({:insert_verdict, attrs}, _from, %{conn: conn} = state) do
    {:reply, insert_verdict_records(conn, [attrs]), state}
  end

  def handle_call({:insert_verdicts, attrs_list}, _from, %{conn: conn} = state) do
    {:reply, insert_verdict_records(conn, attrs_list), state}
  end

  def handle_call({:insert_cost, attrs}, _from, %{conn: conn} = state) do
    {:reply, insert_cost_records(conn, [attrs]), state}
  end

  def handle_call({:insert_costs, attrs_list}, _from, %{conn: conn} = state) do
    {:reply, insert_cost_records(conn, attrs_list), state}
  end

  def handle_call({:insert_event, attrs}, _from, %{conn: conn} = state) do
    sql = """
    INSERT INTO events (review_run_id, kind, payload_json)
    VALUES (?1, ?2, ?3)
    """

    payload =
      case attrs[:payload] do
        p when is_binary(p) ->
          p

        p when is_map(p) ->
          case Jason.encode(p) do
            {:ok, json} ->
              json

            {:error, reason} ->
              Logger.warning("Failed to encode event payload: #{inspect(reason)}")
              "{}"
          end

        _ ->
          "{}"
      end

    bindings = [attrs[:review_run_id], attrs[:kind] || "unknown", payload]
    result = exec(conn, sql, bindings)
    {:reply, result, state}
  end

  def handle_call({:list_events, run_id}, _from, %{conn: conn} = state) do
    sql = """
    SELECT kind, payload_json FROM events WHERE review_run_id = ?1 ORDER BY inserted_at
    """

    result =
      query_rows(conn, sql, [run_id], fn [kind, payload] ->
        %{kind: kind, payload: safe_decode(payload)}
      end)

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

  def handle_call({:review_run_verdicts, run_id}, _from, %{conn: conn} = state) do
    sql = """
    SELECT reviewer, perspective, verdict, confidence, summary, findings_json
    FROM verdicts
    WHERE review_run_id = ?1
    ORDER BY inserted_at, id
    """

    result = query_rows(conn, sql, [run_id], &parse_verdict_row/1)
    {:reply, result, state}
  end

  @impl true
  def terminate(_reason, %{conn: conn}) do
    Exqlite.Sqlite3.close(conn)
    :ok
  end

  # --- Statement lifecycle helpers ---

  # Prepare, bind, execute callback, release. The core abstraction that
  # eliminates the prepare/try/bind/after/release boilerplate.
  defp with_statement(conn, sql, bindings, fun) do
    with {:ok, stmt} <- Exqlite.Sqlite3.prepare(conn, sql) do
      try do
        with :ok <- bind_if_needed(stmt, bindings) do
          fun.(conn, stmt)
        end
      after
        Exqlite.Sqlite3.release(conn, stmt)
      end
    end
  end

  # Execute a write statement (bind + step to :done), then run an optional
  # post-step callback. Returns :ok when no callback is given.
  defp exec(conn, sql, bindings, after_fn \\ nil) do
    with_statement(conn, sql, bindings, fn conn, stmt ->
      case Exqlite.Sqlite3.step(conn, stmt) do
        :done ->
          if after_fn, do: after_fn.(conn, stmt), else: :ok

        {:error, _} = err ->
          err

        other ->
          {:error, other}
      end
    end)
  end

  defp changes_count(conn) do
    with {:ok, cs} <- Exqlite.Sqlite3.prepare(conn, "SELECT changes()"),
         {:row, [count]} <- Exqlite.Sqlite3.step(conn, cs) do
      Exqlite.Sqlite3.release(conn, cs)
      {:ok, count}
    else
      _ -> {:ok, 0}
    end
  end

  # --- Query helpers ---

  defp query_rows(conn, sql, bindings, row_parser) do
    with_statement(conn, sql, bindings, fn conn, stmt ->
      collect_parsed_rows(conn, stmt, row_parser, [])
    end)
  end

  defp bind_if_needed(_stmt, []), do: :ok
  defp bind_if_needed(stmt, bindings), do: Exqlite.Sqlite3.bind(stmt, bindings)

  defp collect_rows(conn, statement, acc) do
    case Exqlite.Sqlite3.step(conn, statement) do
      {:row, [name]} -> collect_rows(conn, statement, [name | acc])
      :done -> {:ok, Enum.reverse(acc)}
      {:error, reason} -> {:error, reason}
    end
  end

  defp collect_parsed_rows(conn, stmt, parser, acc) do
    case Exqlite.Sqlite3.step(conn, stmt) do
      {:row, values} -> collect_parsed_rows(conn, stmt, parser, [parser.(values) | acc])
      :done -> {:ok, Enum.reverse(acc)}
      {:error, reason} -> {:error, reason}
    end
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

  defp ensure_schema_ready(conn) do
    with :ok <- ensure_schema_tables(conn),
         {:ok, verdict_columns} <- table_columns(conn, "verdicts") do
      migrate_verdicts_table(conn, verdict_columns)
    end
  end

  defp table_columns(conn, table_name) when table_name in @known_tables do
    sql = "PRAGMA table_info(#{table_name})"

    with_statement(conn, sql, [], fn conn, stmt ->
      collect_table_columns(conn, stmt, [])
    end)
  end

  defp table_columns(_conn, table_name), do: {:error, {:unknown_table, table_name}}

  defp collect_table_columns(conn, stmt, acc) do
    case Exqlite.Sqlite3.step(conn, stmt) do
      {:row, [_cid, name | _rest]} -> collect_table_columns(conn, stmt, [name | acc])
      :done -> {:ok, Enum.reverse(acc)}
      {:error, reason} -> {:error, reason}
    end
  end

  defp migrate_verdicts_table(conn, existing_columns) do
    statements =
      Enum.flat_map(@verdicts_column_migrations, fn {column, statement} ->
        if column in existing_columns, do: [], else: [statement]
      end)

    if statements == [] do
      :ok
    else
      transaction(conn, fn ->
        Enum.reduce_while(statements, :ok, fn statement, :ok ->
          case Exqlite.Sqlite3.execute(conn, statement) do
            :ok -> {:cont, :ok}
            {:error, reason} -> {:halt, {:error, reason}}
          end
        end)
      end)
    end
  end

  # --- Data helpers ---

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
      {:ok, val} ->
        val

      {:error, reason} ->
        Logger.warning("failed to decode persisted JSON payload: #{inspect(reason)}")
        nil
    end
  end

  defp normalize_findings(findings) when is_list(findings) do
    {normalized, dropped} =
      Enum.reduce(findings, {[], 0}, fn finding, {acc, dropped} ->
        case normalize_finding(finding) do
          {:ok, normalized_finding} -> {[normalized_finding | acc], dropped}
          :drop -> {acc, dropped + 1}
        end
      end)

    if dropped > 0 do
      Logger.warning("dropped #{dropped} invalid reviewer finding(s) during normalization")
    end

    Enum.reverse(normalized)
  end

  defp normalize_findings(nil), do: []

  defp normalize_findings(_findings) do
    Logger.warning("dropping invalid findings payload during read normalization: expected list")
    []
  end

  defp normalize_finding(%_{} = finding), do: finding |> Map.from_struct() |> normalize_finding()

  defp normalize_finding(finding) when is_map(finding) do
    normalized =
      finding
      |> Enum.reject(fn {_key, value} -> is_nil(value) end)
      |> Map.new()

    if map_size(normalized) == 0, do: :drop, else: {:ok, normalized}
  end

  defp normalize_finding(_), do: :drop

  defp parse_cost_row([
         reviewer,
         model,
         prompt_tokens,
         completion_tokens,
         cost_usd,
         duration_ms,
         status,
         is_fallback
       ]) do
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

  defp parse_verdict_row([reviewer, perspective, verdict, confidence, summary, findings_json]) do
    findings =
      findings_json
      |> safe_decode()
      |> normalize_findings()

    %{
      reviewer: reviewer,
      perspective: perspective,
      verdict: verdict,
      confidence: normalize_confidence(confidence),
      summary: summary,
      findings: findings
    }
  end

  defp normalize_confidence(confidence) when is_float(confidence), do: confidence
  defp normalize_confidence(confidence) when is_integer(confidence), do: confidence / 1.0
  defp normalize_confidence(nil), do: 0.0

  defp normalize_confidence(confidence) do
    Logger.warning("normalizing unexpected confidence value to 0.0: #{inspect(confidence)}")
    0.0
  end

  defp insert_verdict_records(_conn, []), do: :ok

  defp insert_verdict_records(conn, attrs_list) do
    with {:ok, bindings_list} <- prepare_verdict_bindings(attrs_list) do
      transaction(conn, fn ->
        Enum.reduce_while(bindings_list, :ok, fn bindings, :ok ->
          case exec(conn, verdict_insert_sql(), bindings) do
            :ok -> {:cont, :ok}
            {:error, reason} -> {:halt, {:error, reason}}
          end
        end)
      end)
    end
  end

  defp prepare_verdict_bindings(attrs_list) do
    Enum.reduce_while(attrs_list, {:ok, []}, fn attrs, {:ok, acc} ->
      case prepare_verdict_binding(attrs) do
        {:ok, bindings} -> {:cont, {:ok, [bindings | acc]}}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
    |> then(fn
      {:ok, bindings} -> {:ok, Enum.reverse(bindings)}
      other -> other
    end)
  end

  defp prepare_verdict_binding(attrs) do
    with {:ok, findings} <- validate_findings(Map.get(attrs, :findings, [])),
         {:ok, findings_json} <- Jason.encode(findings) do
      {:ok,
       [
         attrs[:review_run_id],
         attrs[:reviewer] || "",
         attrs[:verdict] || "SKIP",
         attrs[:perspective] || "",
         normalize_confidence(attrs[:confidence]),
         attrs[:summary] || "",
         findings_json
       ]}
    else
      {:error, :not_a_list} ->
        Logger.warning("invalid findings payload on write: expected list")
        {:error, {:invalid_findings, :not_a_list}}

      {:error, reason} ->
        {:error, {:invalid_findings, reason}}
    end
  end

  defp validate_findings(findings) when is_list(findings), do: {:ok, normalize_findings(findings)}
  defp validate_findings(_findings), do: {:error, :not_a_list}

  defp verdict_insert_sql do
    """
    INSERT INTO verdicts
      (review_run_id, reviewer, verdict, perspective, confidence, summary, findings_json)
    VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
    """
  end

  defp insert_cost_records(_conn, []), do: :ok

  defp insert_cost_records(conn, attrs_list) do
    attrs_list
    |> Enum.map(&prepare_cost_binding/1)
    |> then(fn bindings_list ->
      transaction(conn, fn ->
        Enum.reduce_while(bindings_list, :ok, fn bindings, :ok ->
          case exec(conn, cost_insert_sql(), bindings) do
            :ok -> {:cont, :ok}
            {:error, reason} -> {:halt, {:error, reason}}
          end
        end)
      end)
    end)
  end

  defp prepare_cost_binding(attrs) do
    [
      attrs[:review_run_id],
      attrs[:reviewer] || "",
      attrs[:model] || "",
      attrs[:prompt_tokens] || 0,
      attrs[:completion_tokens] || 0,
      attrs[:cost_usd] || 0.0,
      attrs[:duration_ms] || 0,
      to_string(attrs[:status] || "success"),
      if(attrs[:is_fallback], do: 1, else: 0)
    ]
  end

  defp cost_insert_sql do
    """
    INSERT INTO review_costs
      (review_run_id, reviewer, model, prompt_tokens, completion_tokens,
       cost_usd, duration_ms, status, is_fallback)
    VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
    """
  end

  defp transaction(conn, fun) do
    with :ok <- Exqlite.Sqlite3.execute(conn, "BEGIN IMMEDIATE") do
      try do
        case fun.() do
          :ok = result -> commit_transaction(conn, result)
          {:ok, _} = result -> commit_transaction(conn, result)
          {:error, _} = result -> rollback_transaction(conn, result)
          other -> rollback_transaction(conn, {:error, other})
        end
      rescue
        error ->
          _ = Exqlite.Sqlite3.execute(conn, "ROLLBACK")
          reraise error, __STACKTRACE__
      catch
        kind, reason ->
          _ = Exqlite.Sqlite3.execute(conn, "ROLLBACK")
          :erlang.raise(kind, reason, __STACKTRACE__)
      end
    end
  end

  defp commit_transaction(conn, result) do
    case Exqlite.Sqlite3.execute(conn, "COMMIT") do
      :ok -> result
      {:error, reason} -> {:error, reason}
    end
  end

  defp rollback_transaction(conn, result) do
    _ = Exqlite.Sqlite3.execute(conn, "ROLLBACK")
    result
  end
end
