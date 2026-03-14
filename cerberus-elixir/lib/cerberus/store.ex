defmodule Cerberus.Store do
  @moduledoc false

  use GenServer

  @schema_statements [
    """
    CREATE TABLE IF NOT EXISTS review_runs (
      id INTEGER PRIMARY KEY,
      pr_number INTEGER,
      status TEXT NOT NULL,
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
    """
  ]

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts)
  end

  @spec ensure_schema(pid() | atom()) :: :ok | {:error, term()}
  def ensure_schema(store) do
    GenServer.call(store, :ensure_schema)
  end

  @spec table_names(pid() | atom()) :: {:ok, [String.t()]} | {:error, term()}
  def table_names(store) do
    GenServer.call(store, :table_names)
  end

  @impl true
  def init(opts) do
    database_path = Keyword.get(opts, :database_path, Cerberus.database_path())

    with :ok <- ensure_database_directory(database_path),
         {:ok, conn} <- Exqlite.Sqlite3.open(database_path),
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

  @impl true
  def terminate(_reason, %{conn: conn}) do
    Exqlite.Sqlite3.close(conn)
    :ok
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
end
