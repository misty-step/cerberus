defmodule Cerberus.StoreReviewRunTest do
  use ExUnit.Case, async: true

  alias Cerberus.Store

  setup do
    db_path =
      Path.join(
        System.tmp_dir!(),
        "cerberus_store_rr_test_#{System.unique_integer([:positive])}.db"
      )

    {:ok, store} = Store.start_link(database_path: db_path)
    on_exit(fn -> File.rm(db_path) end)
    %{store: store}
  end

  describe "create_review_run/2" do
    test "returns integer ID", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})
      assert is_integer(id)
      assert id > 0
    end

    test "assigns incrementing IDs", %{store: store} do
      id1 = Store.create_review_run(store, %{repo: "a/b", pr_number: 1, head_sha: "sha1"})
      id2 = Store.create_review_run(store, %{repo: "a/b", pr_number: 2, head_sha: "sha2"})
      assert id2 > id1
    end
  end

  describe "get_review_run/2" do
    test "retrieves created run", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})
      assert {:ok, run} = Store.get_review_run(store, id)
      assert run.review_id == id
      assert run.repo == "org/repo"
      assert run.pr_number == 42
      assert run.head_sha == "abc123"
      assert run.status == "queued"
      assert run.aggregated_verdict == nil
    end

    test "returns not_found for missing ID", %{store: store} do
      assert {:error, :not_found} = Store.get_review_run(store, 99999)
    end
  end

  describe "update_review_run/3" do
    test "updates status", %{store: store} do
      id = Store.create_review_run(store, %{repo: "a/b", pr_number: 1, head_sha: "sha1"})
      assert :ok = Store.update_review_run(store, id, %{status: "running"})

      {:ok, run} = Store.get_review_run(store, id)
      assert run.status == "running"
    end

    test "updates aggregated verdict JSON", %{store: store} do
      id = Store.create_review_run(store, %{repo: "a/b", pr_number: 1, head_sha: "sha1"})
      verdict = %{"verdict" => "PASS", "summary" => "All clear"}

      assert :ok =
               Store.update_review_run(store, id, %{
                 status: "completed",
                 aggregated_verdict_json: Jason.encode!(verdict),
                 completed_at: "2026-03-15T12:00:00Z"
               })

      {:ok, run} = Store.get_review_run(store, id)
      assert run.status == "completed"
      assert run.aggregated_verdict == verdict
      assert run.completed_at == "2026-03-15T12:00:00Z"
    end

    test "handles invalid JSON in aggregated_verdict_json gracefully", %{store: store} do
      id = Store.create_review_run(store, %{repo: "a/b", pr_number: 1, head_sha: "sha1"})
      Store.update_review_run(store, id, %{aggregated_verdict_json: "not-json"})

      {:ok, run} = Store.get_review_run(store, id)
      assert run.aggregated_verdict == nil
    end

    test "no-op when no fields provided", %{store: store} do
      id = Store.create_review_run(store, %{repo: "a/b", pr_number: 1, head_sha: "sha1"})
      assert :ok = Store.update_review_run(store, id, %{})

      {:ok, run} = Store.get_review_run(store, id)
      assert run.status == "queued"
    end

    test "returns not_found for non-existent ID", %{store: store} do
      assert {:error, :not_found} = Store.update_review_run(store, 99999, %{status: "running"})
    end
  end

  describe "verdict persistence" do
    test "stores and loads per-reviewer verdict details", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      assert :ok =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.85,
                 summary: "Potential nil dereference",
                 findings: [
                   %{
                     severity: "major",
                     category: "correctness",
                     file: "lib/foo.ex",
                     line: 12,
                     title: "Nil guard missing",
                     description: "The code dereferences a maybe-nil value.",
                     suggestion: "Guard the value before dereferencing."
                   }
                 ]
               })

      assert {:ok, [stored]} = Store.review_run_verdicts(store, id)
      assert stored.reviewer == "trace"
      assert stored.perspective == "correctness"
      assert stored.verdict == "WARN"
      assert stored.confidence == 0.85
      assert stored.summary == "Potential nil dereference"

      assert stored.findings == [
               %{
                 "severity" => "major",
                 "category" => "correctness",
                 "file" => "lib/foo.ex",
                 "line" => 12,
                 "title" => "Nil guard missing",
                 "description" => "The code dereferences a maybe-nil value.",
                 "suggestion" => "Guard the value before dereferencing."
               }
             ]
    end

    test "returns empty verdicts list for unknown review run", %{store: store} do
      assert {:ok, []} = Store.review_run_verdicts(store, 99999)
    end

    test "drops invalid findings before storing", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      assert :ok =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.4,
                 summary: "Mixed findings",
                 findings: [
                   %{
                     severity: "minor",
                     category: "correctness",
                     file: "lib/foo.ex",
                     line: 9,
                     title: "Guard missing",
                     description: "Add a guard clause."
                   },
                   nil,
                   123
                 ]
               })

      assert {:ok, [stored]} = Store.review_run_verdicts(store, id)

      assert stored.findings == [
               %{
                 "severity" => "minor",
                 "category" => "correctness",
                 "file" => "lib/foo.ex",
                 "line" => 9,
                 "title" => "Guard missing",
                 "description" => "Add a guard clause."
               }
             ]
    end
  end
end
