defmodule Cerberus.StoreTest do
  use ExUnit.Case, async: false

  defp with_raw_db(database_path, fun) do
    {:ok, conn} = Exqlite.Sqlite3.open(database_path)

    try do
      fun.(conn)
    after
      Exqlite.Sqlite3.close(conn)
    end
  end

  test "creates the review run tables on boot" do
    database_path =
      Path.join(System.tmp_dir!(), "cerberus-store-#{System.unique_integer([:positive])}.db")

    on_exit(fn -> File.rm(database_path) end)

    store = start_supervised!({Cerberus.Store, database_path: database_path})

    assert {:ok, tables} = Cerberus.Store.table_names(store)
    assert "events" in tables
    assert "review_runs" in tables
    assert "verdicts" in tables
  end

  test "migrates legacy verdict table columns on boot" do
    database_path =
      Path.join(
        System.tmp_dir!(),
        "cerberus-store-legacy-#{System.unique_integer([:positive])}.db"
      )

    on_exit(fn -> File.rm(database_path) end)

    with_raw_db(database_path, fn conn ->
      :ok =
        Exqlite.Sqlite3.execute(
          conn,
          """
          CREATE TABLE verdicts (
            id INTEGER PRIMARY KEY,
            review_run_id INTEGER NOT NULL,
            reviewer TEXT NOT NULL,
            verdict TEXT NOT NULL,
            inserted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
          )
          """
        )
    end)

    store = start_supervised!({Cerberus.Store, database_path: database_path})

    review_id =
      Cerberus.Store.create_review_run(store, %{
        repo: "org/repo",
        pr_number: 42,
        head_sha: "abc123"
      })

    assert :ok =
             Cerberus.Store.insert_verdict(store, %{
               review_run_id: review_id,
               reviewer: "trace",
               perspective: "correctness",
               verdict: "PASS",
               confidence: 0.9,
               summary: "Looks good",
               findings: []
             })

    assert {:ok, [stored]} = Cerberus.Store.review_run_verdicts(store, review_id)
    assert stored.perspective == "correctness"
    assert stored.summary == "Looks good"
  end
end
