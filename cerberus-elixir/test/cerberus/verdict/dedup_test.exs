defmodule Cerberus.Verdict.DedupTest do
  use ExUnit.Case, async: true

  alias Cerberus.Verdict.Dedup
  alias Cerberus.Verdict.Finding

  defp finding(overrides \\ %{}) do
    Map.merge(
      %Finding{
        severity: "major",
        category: "logic",
        file: "lib/foo.ex",
        line: 42,
        title: "Unchecked nil return",
        description: "Function may return nil but caller assumes non-nil.",
        suggestion: nil,
        evidence: nil,
        scope: nil,
        suggestion_verified: nil
      },
      overrides
    )
  end

  # --- group_findings/1 ---

  describe "group_findings/1" do
    test "single finding passes through" do
      result = Dedup.group_findings(%{"trace" => [finding()]})
      assert length(result) == 1
      assert hd(result).reviewers == ["trace"]
    end

    test "same finding from two reviewers merges" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding()],
          "guard" => [finding()]
        })

      assert length(result) == 1
      assert Enum.sort(hd(result).reviewers) == ["guard", "trace"]
    end

    test "different files are not merged" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding()],
          "guard" => [finding(%{file: "lib/bar.ex"})]
        })

      assert length(result) == 2
    end

    test "different categories are not merged" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding()],
          "guard" => [finding(%{category: "security"})]
        })

      assert length(result) == 2
    end

    test "different titles with token overlap merge when lines within ±3" do
      f1 =
        finding(%{
          line: 42,
          title: "Missing error handling in parser",
          description: "The parser function fails on bad input"
        })

      f2 =
        finding(%{
          line: 44,
          title: "Parser lacks error handling",
          description: "Bad input causes parser function to crash"
        })

      result = Dedup.group_findings(%{"trace" => [f1], "guard" => [f2]})
      assert length(result) == 1
    end

    test "token overlap does not merge when lines more than 3 apart" do
      f1 =
        finding(%{
          line: 10,
          title: "Missing error handling in parser",
          description: "The parser function fails on bad input"
        })

      f2 =
        finding(%{
          line: 50,
          title: "Parser lacks error handling",
          description: "Bad input causes parser function to crash"
        })

      result = Dedup.group_findings(%{"trace" => [f1], "guard" => [f2]})
      assert length(result) == 2
    end

    test "same title different positive lines are not merged even if close" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding(%{line: 42})],
          "guard" => [finding(%{line: 44})]
        })

      assert length(result) == 2
    end

    test "zero line allows merge on title match" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding(%{line: 42})],
          "guard" => [finding(%{line: 0})]
        })

      assert length(result) == 1
    end

    test "worst severity wins on merge" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding(%{severity: "minor"})],
          "guard" => [finding(%{severity: "critical"})]
        })

      assert hd(result).severity == "critical"
    end

    test "earliest positive line wins on merge" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding(%{line: 44})],
          "guard" => [finding(%{line: 42})]
        })

      assert hd(result).line == 42
    end

    test "longest text wins for description" do
      short = finding(%{description: "Short."})
      long = finding(%{description: "A much longer description with more detail."})

      result = Dedup.group_findings(%{"trace" => [short], "guard" => [long]})
      assert hd(result).description == "A much longer description with more detail."
    end

    test "accumulates and sorts reviewer names" do
      result =
        Dedup.group_findings(%{
          "craft" => [finding()],
          "atlas" => [finding()],
          "trace" => [finding()]
        })

      assert hd(result).reviewers == ["atlas", "craft", "trace"]
    end

    test "empty input returns empty list" do
      assert Dedup.group_findings(%{}) == []
    end

    test "N/A file normalizes to empty for matching" do
      result =
        Dedup.group_findings(%{
          "trace" => [finding(%{file: "N/A", line: 0})],
          "guard" => [finding(%{file: "N/A", line: 0})]
        })

      assert length(result) == 1
    end
  end

  # --- Token overlap ---

  describe "token-based matching" do
    test "similar descriptions merge via token overlap" do
      f1 =
        finding(%{
          title: "Missing error handling in parser",
          description: "The parser function does not handle malformed input gracefully"
        })

      f2 =
        finding(%{
          title: "Parser lacks error handling",
          description: "Malformed input causes the parser function to crash without recovery"
        })

      result = Dedup.group_findings(%{"trace" => [f1], "guard" => [f2]})
      assert length(result) == 1
    end

    test "completely different descriptions do not merge" do
      f1 =
        finding(%{
          title: "SQL injection vulnerability",
          description: "User input concatenated into SQL query string"
        })

      f2 =
        finding(%{
          title: "Missing test coverage",
          description: "Authentication module has zero unit tests"
        })

      result = Dedup.group_findings(%{"trace" => [f1], "guard" => [f2]})
      assert length(result) == 2
    end
  end

  # --- stemming behavior (tested through group_findings) ---

  describe "stemming in token matching" do
    test "stemmed forms merge findings (-ing, -ed variants)" do
      f1 =
        finding(%{
          title: "Handling errors incorrectly",
          description: "The parsed output is handled without validation"
        })

      f2 =
        finding(%{
          title: "Error handler missing validation",
          description: "Parsed results processed without checks"
        })

      result = Dedup.group_findings(%{"trace" => [f1], "guard" => [f2]})
      assert length(result) == 1
    end

    test "stop words and short tokens do not create false merges" do
      f1 = finding(%{title: "SQL injection risk", description: "User input used in query"})

      f2 =
        finding(%{
          title: "Missing test coverage",
          description: "This module has no tests for the same area"
        })

      result = Dedup.group_findings(%{"trace" => [f1], "guard" => [f2]})
      assert length(result) == 2
    end
  end
end
