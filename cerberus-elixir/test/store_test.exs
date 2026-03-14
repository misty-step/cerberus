defmodule Cerberus.StoreTest do
  use ExUnit.Case, async: false

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
end
