defmodule Cerberus.StoreReviewRunTest do
  use ExUnit.Case, async: true

  alias Cerberus.Store
  alias Cerberus.Verdict.Finding

  @max_findings_json_bytes 65_536

  defp with_raw_db(database_path, fun) do
    {:ok, conn} = Exqlite.Sqlite3.open(database_path)

    try do
      fun.(conn)
    after
      Exqlite.Sqlite3.close(conn)
    end
  end

  setup do
    db_path =
      Path.join(
        System.tmp_dir!(),
        "cerberus_store_rr_test_#{System.unique_integer([:positive])}.db"
      )

    {:ok, store} = Store.start_link(database_path: db_path)
    on_exit(fn -> File.rm(db_path) end)
    %{store: store, db_path: db_path}
  end

  defp persisted_finding(attrs) do
    Map.merge(
      %{
        severity: "major",
        category: "correctness",
        file: "lib/foo.ex",
        line: 12,
        title: "Nil guard missing",
        description: "The code dereferences a maybe-nil value.",
        suggestion: "Guard the value before dereferencing."
      },
      attrs
    )
  end

  defp encoded_findings_size(findings) do
    findings
    |> Jason.encode!()
    |> byte_size()
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

    test "rejects malformed findings before storing", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      assert {:error, {:invalid_findings, {:invalid_finding, 1, {:non_scalar_value, "metadata"}}}} =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.4,
                 summary: "Mixed findings",
                 findings: [
                   persisted_finding(%{
                     severity: "minor",
                     line: 9,
                     title: "Guard missing",
                     description: "Add a guard clause."
                   }),
                   persisted_finding(%{metadata: %{nested: true}})
                 ]
               })

      assert {:ok, []} = Store.review_run_verdicts(store, id)
    end

    test "normalizes struct findings before storing", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      assert :ok =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.4,
                 summary: "Struct finding",
                 findings: [
                   %Finding{
                     severity: "major",
                     category: "correctness",
                     file: "lib/foo.ex",
                     line: 18,
                     title: "Guard missing",
                     description: "Add a guard clause.",
                     suggestion: "Pattern match before dereferencing."
                   }
                 ]
               })

      assert {:ok, [stored]} = Store.review_run_verdicts(store, id)

      assert stored.findings == [
               %{
                 "severity" => "major",
                 "category" => "correctness",
                 "file" => "lib/foo.ex",
                 "line" => 18,
                 "title" => "Guard missing",
                 "description" => "Add a guard clause.",
                 "suggestion" => "Pattern match before dereferencing."
               }
             ]
    end

    test "rejects findings payloads that exceed the byte limit", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      base_finding = persisted_finding(%{description: ""})
      padding = @max_findings_json_bytes - encoded_findings_size([base_finding])

      oversized_finding =
        persisted_finding(%{
          description: String.duplicate("x", padding + 1)
        })

      assert {:error, {:invalid_findings, {:payload_too_large, size, @max_findings_json_bytes}}} =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.4,
                 summary: "Oversized findings payload",
                 findings: [oversized_finding]
               })

      assert size == encoded_findings_size([oversized_finding])
      assert {:ok, []} = Store.review_run_verdicts(store, id)
    end

    test "accepts findings payloads at the byte limit", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      base_finding = persisted_finding(%{description: ""})
      padding = @max_findings_json_bytes - encoded_findings_size([base_finding])

      limit_finding = persisted_finding(%{description: String.duplicate("x", padding)})

      assert encoded_findings_size([limit_finding]) == @max_findings_json_bytes

      assert :ok =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.4,
                 summary: "Boundary findings payload",
                 findings: [limit_finding]
               })

      assert {:ok, [stored]} = Store.review_run_verdicts(store, id)
      assert stored.summary == "Boundary findings payload"

      assert stored.findings == [
               Map.new(limit_finding, fn {key, value} -> {Atom.to_string(key), value} end)
             ]
    end

    test "batch verdict inserts are atomic when one payload is invalid", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      assert {:error, {:invalid_findings, {:invalid_finding, 0, {:non_scalar_value, "raw"}}}} =
               Store.insert_verdicts(store, [
                 %{
                   review_run_id: id,
                   reviewer: "trace",
                   perspective: "correctness",
                   verdict: "PASS",
                   confidence: 1.0,
                   summary: "Healthy verdict",
                   findings: []
                 },
                 %{
                   review_run_id: id,
                   reviewer: "guard",
                   perspective: "security",
                   verdict: "WARN",
                   confidence: 0.5,
                   summary: "Bad verdict payload",
                   findings: [%{raw: self()}]
                 }
               ])

      assert {:ok, []} = Store.review_run_verdicts(store, id)
    end

    test "batch verdict inserts roll back on SQL errors", %{store: store, db_path: db_path} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      with_raw_db(db_path, fn conn ->
        :ok =
          Exqlite.Sqlite3.execute(
            conn,
            """
            CREATE TRIGGER verdicts_abort_on_guard
            BEFORE INSERT ON verdicts
            WHEN NEW.reviewer = 'guard'
            BEGIN
              SELECT RAISE(ABORT, 'forced verdict insert failure');
            END;
            """
          )
      end)

      assert {:error, reason} =
               Store.insert_verdicts(store, [
                 %{
                   review_run_id: id,
                   reviewer: "trace",
                   perspective: "correctness",
                   verdict: "PASS",
                   confidence: 1.0,
                   summary: "Healthy verdict",
                   findings: []
                 },
                 %{
                   review_run_id: id,
                   reviewer: "guard",
                   perspective: "security",
                   verdict: "WARN",
                   confidence: 0.5,
                   summary: "Triggered rollback",
                   findings: []
                 }
               ])

      assert inspect(reason) =~ "forced verdict insert failure"
      assert {:ok, []} = Store.review_run_verdicts(store, id)
    end

    test "returns an error when findings contain non-scalar values", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      assert {:error, {:invalid_findings, {:invalid_finding, 0, {:non_scalar_value, "raw"}}}} =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.4,
                 summary: "Unserializable finding payload",
                 findings: [%{raw: self()}]
               })

      assert :ok =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "PASS",
                 confidence: 1.0,
                 summary: "Store still healthy",
                 findings: []
               })

      assert {:ok, [stored]} = Store.review_run_verdicts(store, id)
      assert stored.summary == "Store still healthy"
    end

    test "rejects non-list findings payloads on write", %{store: store} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      assert {:error, {:invalid_findings, :not_a_list}} =
               Store.insert_verdict(store, %{
                 review_run_id: id,
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "WARN",
                 confidence: 0.4,
                 summary: "Malformed findings payload",
                 findings: %{oops: true}
               })

      assert {:ok, []} = Store.review_run_verdicts(store, id)
    end

    test "normalizes malformed findings on the read path", %{store: store, db_path: db_path} do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      with_raw_db(db_path, fn conn ->
        :ok =
          Exqlite.Sqlite3.execute(
            conn,
            """
            INSERT INTO verdicts
              (review_run_id, reviewer, verdict, perspective, confidence, summary, findings_json)
            VALUES (
              #{id},
              'trace',
              'WARN',
              'correctness',
              0.3,
              'Malformed findings payload',
              '[null, 123, {}, {\"severity\":\"minor\",\"category\":\"correctness\",\"file\":\"lib/foo.ex\",\"line\":9,\"title\":\"Valid\",\"description\":\"kept\"}, {\"severity\":\"minor\",\"metadata\":{\"nested\":true}}]'
            )
            """
          )
      end)

      assert {:ok, [stored]} = Store.review_run_verdicts(store, id)

      assert stored.findings == [
               %{
                 "severity" => "minor",
                 "category" => "correctness",
                 "file" => "lib/foo.ex",
                 "line" => 9,
                 "title" => "Valid",
                 "description" => "kept"
               }
             ]
    end

    test "normalizes integer and invalid confidence values on the read path", %{
      store: store,
      db_path: db_path
    } do
      id = Store.create_review_run(store, %{repo: "org/repo", pr_number: 42, head_sha: "abc123"})

      with_raw_db(db_path, fn conn ->
        :ok =
          Exqlite.Sqlite3.execute(
            conn,
            """
            INSERT INTO verdicts
              (review_run_id, reviewer, verdict, perspective, confidence, summary, findings_json)
            VALUES
              (#{id}, 'trace', 'PASS', 'correctness', 1, 'Integer confidence', '[]'),
              (#{id}, 'guard', 'WARN', 'security', 'bogus', 'Invalid confidence', '[]')
            """
          )
      end)

      assert {:ok, verdicts} = Store.review_run_verdicts(store, id)

      assert Enum.sort_by(verdicts, & &1.reviewer) == [
               %{
                 reviewer: "guard",
                 perspective: "security",
                 verdict: "WARN",
                 confidence: 0.0,
                 summary: "Invalid confidence",
                 findings: []
               },
               %{
                 reviewer: "trace",
                 perspective: "correctness",
                 verdict: "PASS",
                 confidence: 1.0,
                 summary: "Integer confidence",
                 findings: []
               }
             ]
    end
  end
end
