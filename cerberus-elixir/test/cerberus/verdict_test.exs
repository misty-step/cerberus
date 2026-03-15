defmodule Cerberus.VerdictTest do
  use ExUnit.Case, async: true

  alias Cerberus.Verdict
  alias Cerberus.Verdict.Finding

  defp valid_verdict_map do
    %{
      "reviewer" => "trace",
      "perspective" => "correctness",
      "verdict" => "PASS",
      "confidence" => 0.85,
      "summary" => "No significant issues found.",
      "findings" => [],
      "stats" => %{
        "files_reviewed" => 3,
        "files_with_issues" => 0,
        "critical" => 0,
        "major" => 0,
        "minor" => 0,
        "info" => 0
      }
    }
  end

  defp valid_finding_map do
    %{
      "severity" => "major",
      "category" => "logic",
      "file" => "lib/foo.ex",
      "line" => 42,
      "title" => "Unchecked nil return",
      "description" => "Function may return nil but caller assumes non-nil."
    }
  end

  # --- Verdict.parse/1 ---

  describe "parse/1" do
    test "parses valid JSON string" do
      json = Jason.encode!(valid_verdict_map())
      assert {:ok, %Verdict{verdict: "PASS", confidence: 0.85}} = Verdict.parse(json)
    end

    test "extracts JSON from markdown fenced block" do
      text = """
      Some analysis text here.

      ```json
      #{Jason.encode!(valid_verdict_map())}
      ```
      """

      assert {:ok, %Verdict{reviewer: "trace"}} = Verdict.parse(text)
    end

    test "uses last fenced block when multiple present" do
      first = Jason.encode!(Map.put(valid_verdict_map(), "verdict", "FAIL"))
      second = Jason.encode!(valid_verdict_map())

      text = """
      ```json
      #{first}
      ```

      Revised verdict:

      ```json
      #{second}
      ```
      """

      assert {:ok, %Verdict{verdict: "PASS"}} = Verdict.parse(text)
    end

    test "rejects invalid JSON" do
      assert {:error, _} = Verdict.parse("not json at all")
    end

    test "normalizes integer confidence percentage" do
      map = Map.put(valid_verdict_map(), "confidence", 85)
      json = Jason.encode!(map)
      assert {:ok, %Verdict{confidence: 0.85}} = Verdict.parse(json)
    end
  end

  # --- Verdict.validate/1 ---

  describe "validate/1" do
    test "accepts valid verdict map" do
      assert {:ok, %Verdict{}} = Verdict.validate(valid_verdict_map())
    end

    test "accepts all valid verdict values" do
      for v <- ~w(PASS WARN FAIL SKIP) do
        map = Map.put(valid_verdict_map(), "verdict", v)
        assert {:ok, %Verdict{verdict: ^v}} = Verdict.validate(map)
      end
    end

    test "rejects invalid verdict value" do
      map = Map.put(valid_verdict_map(), "verdict", "MAYBE")
      assert {:error, {:invalid_verdict, "MAYBE"}} = Verdict.validate(map)
    end

    test "rejects missing required keys" do
      map = Map.delete(valid_verdict_map(), "summary")
      assert {:error, {:missing_root_keys, ["summary"]}} = Verdict.validate(map)
    end

    test "rejects confidence out of range" do
      map = Map.put(valid_verdict_map(), "confidence", -0.5)
      assert {:error, {:confidence_out_of_range, _}} = Verdict.validate(map)
    end

    test "rejects non-numeric confidence" do
      map = Map.put(valid_verdict_map(), "confidence", "high")
      assert {:error, :confidence_not_number} = Verdict.validate(map)
    end

    test "validates findings within verdict" do
      finding = valid_finding_map()
      map = Map.put(valid_verdict_map(), "findings", [finding])

      assert {:ok, %Verdict{findings: [%Finding{severity: "major"}]}} = Verdict.validate(map)
    end

    test "rejects verdict with invalid findings" do
      bad_finding = Map.delete(valid_finding_map(), "severity")
      map = Map.put(valid_verdict_map(), "findings", [bad_finding])
      assert {:error, {:invalid_findings, _}} = Verdict.validate(map)
    end

    test "rejects missing stats keys" do
      bad_stats = Map.delete(valid_verdict_map()["stats"], "critical")
      map = Map.put(valid_verdict_map(), "stats", bad_stats)
      assert {:error, {:missing_stats_keys, ["critical"]}} = Verdict.validate(map)
    end

    test "rejects non-integer stats values" do
      bad_stats = Map.put(valid_verdict_map()["stats"], "critical", "none")
      map = Map.put(valid_verdict_map(), "stats", bad_stats)
      assert {:error, {:stats_not_integer, ["critical"]}} = Verdict.validate(map)
    end
  end

  # --- Finding.validate/1 ---

  describe "Finding.validate/1" do
    test "accepts valid finding" do
      assert {:ok, %Finding{severity: "major", line: 42}} = Finding.validate(valid_finding_map())
    end

    test "accepts all valid severities" do
      for s <- ~w(critical major minor info) do
        map = Map.put(valid_finding_map(), "severity", s)
        assert {:ok, %Finding{severity: ^s}} = Finding.validate(map)
      end
    end

    test "accepts optional fields" do
      map =
        valid_finding_map()
        |> Map.put("suggestion", "Use pattern matching")
        |> Map.put("evidence", "def foo(nil), do: :error")
        |> Map.put("scope", "diff")
        |> Map.put("suggestion_verified", true)

      assert {:ok, %Finding{suggestion: "Use pattern matching", scope: "diff"}} =
               Finding.validate(map)
    end

    test "rejects invalid severity" do
      map = Map.put(valid_finding_map(), "severity", "urgent")
      assert {:error, {:invalid_severity, "urgent"}} = Finding.validate(map)
    end

    test "rejects missing required field" do
      map = Map.delete(valid_finding_map(), "file")
      assert {:error, {:missing_fields, ["file"]}} = Finding.validate(map)
    end

    test "rejects non-integer line" do
      map = Map.put(valid_finding_map(), "line", "42")
      assert {:error, :line_not_integer} = Finding.validate(map)
    end

    test "rejects invalid scope" do
      map = Map.put(valid_finding_map(), "scope", "global")
      assert {:error, {:invalid_scope, "global"}} = Finding.validate(map)
    end

    test "accepts valid scopes" do
      for s <- ~w(diff defaults-change) do
        map = Map.put(valid_finding_map(), "scope", s)
        assert {:ok, %Finding{scope: ^s}} = Finding.validate(map)
      end
    end

    test "rejects non-boolean suggestion_verified" do
      map = Map.put(valid_finding_map(), "suggestion_verified", "yes")
      assert {:error, :suggestion_verified_not_boolean} = Finding.validate(map)
    end
  end
end
