defmodule Cerberus.Verdict.Aggregator do
  @moduledoc """
  Aggregates reviewer verdicts into a single Cerberus verdict.

  Takes a list of validated `Cerberus.Verdict` structs (one per reviewer) and
  produces an aggregated result with deduped findings, override handling,
  cost calculation, and reserve escalation signals.

  ## Decision Tree

      1. ALL reviewers skipped → SKIP
      2. Any critical FAIL OR 2+ non-critical FAILs (no override) → FAIL
      3. Any WARN or 1+ non-critical FAIL → WARN
      4. Otherwise → PASS

  ## Options

  - `:override` — `%Cerberus.Verdict.Override{}` or `nil`
  - `:confidence_min` — minimum confidence for findings to count (default 0.7)
  - `:usage` — `%{reviewer_name => %{prompt_tokens: n, completion_tokens: n, model: "..."}}` for cost
  """

  alias Cerberus.Verdict
  alias Cerberus.Verdict.{Cost, Dedup, Override}

  @type result :: %{
          verdict: String.t(),
          summary: String.t(),
          reviewers: [Verdict.t()],
          findings: [Dedup.merged()],
          override: Override.t() | nil,
          reserves: [atom()],
          stats: %{
            total: non_neg_integer(),
            fail: non_neg_integer(),
            warn: non_neg_integer(),
            pass: non_neg_integer(),
            skip: non_neg_integer()
          },
          cost: %{total_usd: float(), per_reviewer: %{String.t() => float()}}
        }

  @spec aggregate([Verdict.t()], keyword()) :: result()
  def aggregate(verdicts, opts \\ []) do
    override = Keyword.get(opts, :override)
    confidence_min = Keyword.get(opts, :confidence_min, 0.7)
    usage = Keyword.get(opts, :usage, %{})

    gated = apply_confidence_gating(verdicts, confidence_min)
    findings = dedup_findings(gated)
    classified = classify(gated)
    verdict = decide(classified, override)
    summary = build_summary(classified, override)
    reserves = detect_reserves(gated)
    cost = calculate_costs(usage)

    %{
      verdict: verdict,
      summary: summary,
      reviewers: verdicts,
      findings: findings,
      override: override,
      reserves: reserves,
      stats: classified.stats,
      cost: cost
    }
  end

  # --- Confidence Gating ---

  defp apply_confidence_gating(verdicts, min) do
    Enum.map(verdicts, fn v ->
      if v.confidence >= min do
        v
      else
        # Below threshold: exclude findings from verdict computation
        # but keep the verdict struct for reporting
        %{v | findings: [], verdict: "SKIP"}
      end
    end)
  end

  # --- Dedup ---

  defp dedup_findings(verdicts) do
    findings_by_reviewer =
      Map.new(verdicts, fn v -> {v.reviewer, v.findings} end)

    Dedup.group_findings(findings_by_reviewer)
  end

  # --- Classification ---

  defp classify(verdicts) do
    groups = Enum.group_by(verdicts, & &1.verdict)

    fails = Map.get(groups, "FAIL", [])
    warns = Map.get(groups, "WARN", [])
    skips = Map.get(groups, "SKIP", [])
    passes = Map.get(groups, "PASS", [])

    blocking = Enum.filter(fails, &has_critical?/1)
    non_critical = fails -- blocking

    %{
      fails: fails,
      blocking_fails: blocking,
      non_critical_fails: non_critical,
      warns: warns,
      skips: skips,
      passes: passes,
      stats: %{
        total: length(verdicts),
        fail: length(fails),
        warn: length(warns),
        pass: length(passes),
        skip: length(skips)
      }
    }
  end

  defp has_critical?(verdict) do
    Enum.any?(verdict.findings, &(&1.severity == "critical")) or
      (is_map(verdict.stats) and Map.get(verdict.stats, "critical", 0) > 0)
  end

  # --- Decision ---

  defp decide(classified, override) do
    cond do
      # Override bypasses all logic
      override != nil ->
        "PASS"

      # All reviewers skipped
      classified.stats.total > 0 and classified.stats.skip == classified.stats.total ->
        "SKIP"

      # Critical FAIL or 2+ non-critical FAILs
      classified.blocking_fails != [] or length(classified.non_critical_fails) >= 2 ->
        "FAIL"

      # Any WARN or single non-critical FAIL
      classified.warns != [] or classified.non_critical_fails != [] ->
        "WARN"

      true ->
        "PASS"
    end
  end

  # --- Summary ---

  defp build_summary(classified, override) do
    if override do
      "Override by #{override.actor} for #{override.sha}."
    else
      %{fail: f, warn: w, skip: s} = classified.stats

      parts =
        []
        |> prepend_if(f > 0, "#{f} failure(s)")
        |> prepend_if(w > 0, "#{w} warning(s)")
        |> prepend_if(s > 0, "#{s} skipped")

      case parts do
        [] -> "All reviewers passed."
        _ -> Enum.reverse(parts) |> Enum.join(", ") |> Kernel.<>(".")
      end
    end
  end

  defp prepend_if(list, true, item), do: [item | list]
  defp prepend_if(list, false, _item), do: list

  # --- Reserve Triggers ---

  @reserve_checks [
    {:disagreement, &__MODULE__.disagreement?/1},
    {:low_confidence, &__MODULE__.low_confidence?/1},
    {:critical_weak_evidence, &__MODULE__.critical_weak_evidence?/1}
  ]

  defp detect_reserves(verdicts) do
    for {signal, check} <- @reserve_checks, check.(verdicts), do: signal
  end

  @doc false
  def disagreement?(verdicts) do
    effective = verdicts |> Enum.reject(&(&1.verdict == "SKIP")) |> Enum.map(& &1.verdict)
    "PASS" in effective and "FAIL" in effective
  end

  @doc false
  def low_confidence?(verdicts) do
    Enum.any?(verdicts, &(&1.verdict != "SKIP" and &1.confidence < 0.5))
  end

  @doc false
  def critical_weak_evidence?(verdicts) do
    Enum.any?(verdicts, fn v ->
      Enum.any?(v.findings, fn f ->
        f.severity == "critical" and
          (is_nil(f.evidence) or (is_binary(f.evidence) and String.length(f.evidence) < 10))
      end)
    end)
  end

  # --- Cost ---

  defp calculate_costs(usage) when map_size(usage) == 0 do
    %{total_usd: 0.0, per_reviewer: %{}}
  end

  defp calculate_costs(usage) do
    per_reviewer =
      Map.new(usage, fn {reviewer, u} ->
        model = Map.get(u, :model, "unknown")
        cost = Cost.calculate(u.prompt_tokens, u.completion_tokens, model)
        {reviewer, cost}
      end)

    total = per_reviewer |> Map.values() |> Enum.sum()
    %{total_usd: total, per_reviewer: per_reviewer}
  end
end
