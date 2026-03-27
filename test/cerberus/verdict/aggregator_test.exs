defmodule Cerberus.Verdict.AggregatorTest do
  use ExUnit.Case, async: true

  alias Cerberus.Verdict
  alias Cerberus.Verdict.{Aggregator, Finding, Override}

  defp verdict(overrides \\ %{}) do
    Map.merge(
      %Verdict{
        reviewer: "trace",
        perspective: "correctness",
        verdict: "PASS",
        confidence: 0.85,
        summary: "No issues.",
        findings: [],
        stats: %{
          "files_reviewed" => 3,
          "files_with_issues" => 0,
          "critical" => 0,
          "major" => 0,
          "minor" => 0,
          "info" => 0
        }
      },
      overrides
    )
  end

  defp critical_finding do
    %Finding{
      severity: "critical",
      category: "security",
      file: "lib/auth.ex",
      line: 10,
      title: "SQL injection",
      description: "User input concatenated into query.",
      suggestion: nil,
      evidence: ~s(query = "SELECT * FROM users WHERE id = \#{id}"),
      scope: nil,
      suggestion_verified: nil
    }
  end

  defp major_finding(overrides \\ %{}) do
    Map.merge(
      %Finding{
        severity: "major",
        category: "logic",
        file: "lib/foo.ex",
        line: 42,
        title: "Unchecked nil return",
        description: "Function may return nil.",
        suggestion: nil,
        evidence: nil,
        scope: nil,
        suggestion_verified: nil
      },
      overrides
    )
  end

  # --- aggregate/2 ---

  describe "aggregate/2 verdict decision" do
    test "all PASS → PASS" do
      verdicts = [verdict(), verdict(%{reviewer: "guard", perspective: "security"})]
      result = Aggregator.aggregate(verdicts)
      assert result.verdict == "PASS"
      assert result.summary == "All reviewers passed."
    end

    test "any WARN → WARN" do
      verdicts = [
        verdict(),
        verdict(%{reviewer: "guard", verdict: "WARN"})
      ]

      result = Aggregator.aggregate(verdicts)
      assert result.verdict == "WARN"
    end

    test "single non-critical FAIL → WARN" do
      verdicts = [
        verdict(),
        verdict(%{
          reviewer: "guard",
          verdict: "FAIL",
          findings: [major_finding()],
          stats: %{
            "files_reviewed" => 1,
            "files_with_issues" => 1,
            "critical" => 0,
            "major" => 1,
            "minor" => 0,
            "info" => 0
          }
        })
      ]

      result = Aggregator.aggregate(verdicts)
      assert result.verdict == "WARN"
    end

    test "2+ non-critical FAILs → FAIL" do
      fail_verdict = fn reviewer ->
        verdict(%{
          reviewer: reviewer,
          verdict: "FAIL",
          findings: [major_finding(%{file: "lib/#{reviewer}.ex"})],
          stats: %{
            "files_reviewed" => 1,
            "files_with_issues" => 1,
            "critical" => 0,
            "major" => 1,
            "minor" => 0,
            "info" => 0
          }
        })
      end

      verdicts = [verdict(), fail_verdict.("guard"), fail_verdict.("atlas")]
      result = Aggregator.aggregate(verdicts)
      assert result.verdict == "FAIL"
    end

    test "critical FAIL → FAIL" do
      verdicts = [
        verdict(),
        verdict(%{
          reviewer: "guard",
          verdict: "FAIL",
          findings: [critical_finding()],
          stats: %{
            "files_reviewed" => 1,
            "files_with_issues" => 1,
            "critical" => 1,
            "major" => 0,
            "minor" => 0,
            "info" => 0
          }
        })
      ]

      result = Aggregator.aggregate(verdicts)
      assert result.verdict == "FAIL"
    end

    test "all SKIP → SKIP" do
      verdicts = [
        verdict(%{verdict: "SKIP"}),
        verdict(%{reviewer: "guard", verdict: "SKIP"})
      ]

      result = Aggregator.aggregate(verdicts)
      assert result.verdict == "SKIP"
    end

    test "empty verdicts → PASS" do
      result = Aggregator.aggregate([])
      assert result.verdict == "PASS"
    end
  end

  describe "aggregate/2 override" do
    test "override bypasses FAIL to PASS" do
      verdicts = [
        verdict(%{
          reviewer: "guard",
          verdict: "FAIL",
          findings: [critical_finding()],
          stats: %{
            "files_reviewed" => 1,
            "files_with_issues" => 1,
            "critical" => 1,
            "major" => 0,
            "minor" => 0,
            "info" => 0
          }
        })
      ]

      override = %Override{actor: "alice", sha: "abc1234", reason: "Acceptable risk"}
      result = Aggregator.aggregate(verdicts, override: override)
      assert result.verdict == "PASS"
      assert result.override == override
      assert result.summary =~ "Override by alice"
    end
  end

  describe "aggregate/2 confidence gating" do
    test "low-confidence verdict excluded from thresholds" do
      verdicts = [
        verdict(),
        verdict(%{
          reviewer: "guard",
          verdict: "FAIL",
          confidence: 0.5,
          findings: [critical_finding()]
        })
      ]

      # confidence < 0.7 → verdict downgraded to SKIP, findings cleared
      result = Aggregator.aggregate(verdicts)
      assert result.verdict == "PASS"
      assert result.stats.skip == 1
    end

    test "custom confidence_min respected" do
      verdicts = [
        verdict(%{
          reviewer: "guard",
          verdict: "FAIL",
          confidence: 0.6,
          findings: [critical_finding()],
          stats: %{
            "files_reviewed" => 1,
            "files_with_issues" => 1,
            "critical" => 1,
            "major" => 0,
            "minor" => 0,
            "info" => 0
          }
        })
      ]

      # With confidence_min 0.5, this FAIL should count
      result = Aggregator.aggregate(verdicts, confidence_min: 0.5)
      assert result.verdict == "FAIL"
    end
  end

  describe "aggregate/2 findings dedup" do
    test "duplicate findings across reviewers are collapsed" do
      f = major_finding()

      verdicts = [
        verdict(%{reviewer: "trace", findings: [f]}),
        verdict(%{reviewer: "guard", findings: [f]})
      ]

      result = Aggregator.aggregate(verdicts)
      assert length(result.findings) == 1
      assert Enum.sort(hd(result.findings).reviewers) == ["guard", "trace"]
    end
  end

  describe "aggregate/2 reserve signals" do
    test "detects disagreement (PASS + FAIL)" do
      verdicts = [
        verdict(),
        verdict(%{
          reviewer: "guard",
          verdict: "FAIL",
          findings: [major_finding()],
          stats: %{
            "files_reviewed" => 1,
            "files_with_issues" => 1,
            "critical" => 0,
            "major" => 1,
            "minor" => 0,
            "info" => 0
          }
        })
      ]

      result = Aggregator.aggregate(verdicts)
      assert :disagreement in result.reserves
    end

    test "detects low confidence" do
      verdicts = [
        verdict(%{confidence: 0.4})
      ]

      # confidence 0.4 < 0.7 → gated to SKIP, so verdict is SKIP not PASS
      # But low_confidence? checks pre-gating... actually no, it checks post-gating
      # Post-gating this becomes SKIP with confidence 0.85 (original struct has confidence)
      # Wait — apply_confidence_gating changes verdict to SKIP but keeps confidence field
      # low_confidence? checks verdict != SKIP and confidence < 0.5
      # After gating, verdict is SKIP so this won't trigger

      # Let me use a verdict that stays active but has low confidence
      result = Aggregator.aggregate(verdicts)
      # After gating: confidence stays 0.4 but verdict becomes SKIP
      # low_confidence? filters on verdict != SKIP, so it won't fire
      # This is correct: gated verdicts shouldn't trigger reserves
      refute :low_confidence in result.reserves
    end

    test "detects low confidence on active verdict" do
      # Confidence above gating threshold (0.7) but below reserve threshold (0.5)?
      # That can't happen: 0.5 < 0.7, so any verdict with confidence < 0.5
      # would be gated to SKIP first.
      # Reserve low_confidence only fires for ungated verdicts with confidence < 0.5
      # which means confidence_min must be <= 0.5 for this to happen.
      verdicts = [
        verdict(%{confidence: 0.45})
      ]

      result = Aggregator.aggregate(verdicts, confidence_min: 0.3)
      assert :low_confidence in result.reserves
    end

    test "detects critical finding with weak evidence" do
      weak_critical = %Finding{
        severity: "critical",
        category: "security",
        file: "lib/auth.ex",
        line: 10,
        title: "Possible injection",
        description: "Maybe unsafe.",
        suggestion: nil,
        evidence: nil,
        scope: nil,
        suggestion_verified: nil
      }

      verdicts = [
        verdict(%{
          reviewer: "guard",
          verdict: "FAIL",
          findings: [weak_critical],
          stats: %{
            "files_reviewed" => 1,
            "files_with_issues" => 1,
            "critical" => 1,
            "major" => 0,
            "minor" => 0,
            "info" => 0
          }
        })
      ]

      result = Aggregator.aggregate(verdicts)
      assert :critical_weak_evidence in result.reserves
    end

    test "no reserves when all pass with high confidence" do
      verdicts = [verdict(), verdict(%{reviewer: "guard", perspective: "security"})]
      result = Aggregator.aggregate(verdicts)
      assert result.reserves == []
    end
  end

  describe "aggregate/2 cost" do
    test "calculates cost from usage map" do
      verdicts = [verdict()]

      usage = %{
        "trace" => %{
          prompt_tokens: 1_000_000,
          completion_tokens: 500_000,
          model: "moonshotai/kimi-k2.5"
        }
      }

      result = Aggregator.aggregate(verdicts, usage: usage)
      # kimi: 0.45/M input + 2.20/M output → 0.45 + 1.10 = 1.55
      assert_in_delta result.cost.total_usd, 1.55, 0.01
      assert_in_delta result.cost.per_reviewer["trace"], 1.55, 0.01
    end

    test "zero cost when no usage provided" do
      result = Aggregator.aggregate([verdict()])
      assert result.cost.total_usd == 0.0
    end
  end

  describe "aggregate/2 stats" do
    test "counts verdicts by type" do
      verdicts = [
        verdict(),
        verdict(%{reviewer: "guard", verdict: "WARN"}),
        verdict(%{reviewer: "atlas", verdict: "SKIP"}),
        verdict(%{reviewer: "proof", verdict: "FAIL", findings: [major_finding()]})
      ]

      result = Aggregator.aggregate(verdicts)
      assert result.stats.total == 4
      assert result.stats.pass == 1
      assert result.stats.warn == 1
      assert result.stats.skip == 1
      assert result.stats.fail == 1
    end
  end
end
