defmodule Cerberus.Verdict.Dedup do
  @moduledoc """
  Conservative fuzzy deduplication of findings across reviewers.

  Two findings are equivalent when they share:
  - Same file (normalized)
  - Same category (normalized)
  - Line proximity: |a - b| <= 3 (when both positive)
  - Content match: exact title OR token overlap >= 2 (and >= 40% of smaller set or >= 3)

  On merge: worst severity, earliest positive line, longest text, accumulate reviewers.
  """

  alias Cerberus.Verdict.Finding

  @severity_order %{"critical" => 0, "major" => 1, "minor" => 2, "info" => 3}

  @stop_words MapSet.new(~w(
    a an and at be by for from in into is it of on or same
    that the this to use used using with
  ))

  @min_token_len 4

  @type merged :: %{
          severity: String.t(),
          category: String.t(),
          file: String.t(),
          line: integer(),
          title: String.t(),
          description: String.t(),
          suggestion: String.t() | nil,
          evidence: String.t() | nil,
          reviewers: [String.t()]
        }

  @doc """
  Deduplicate findings across reviewers.

  Takes `%{reviewer_name => [Finding.t()]}`, returns a flat list of merged findings
  sorted by insertion order. Duplicate findings are collapsed with worst severity,
  earliest line, and all contributing reviewer names.
  """
  @spec group_findings(%{String.t() => [Finding.t()]}) :: [merged()]
  def group_findings(findings_by_reviewer) do
    findings_by_reviewer
    |> flatten_and_sort()
    |> Enum.reduce(%{buckets: %{}, entries: %{}, next_id: 0}, fn {reviewer, finding}, state ->
      key = bucket_key(finding)
      ids = Map.get(state.buckets, key, [])

      case find_match(ids, finding, state.entries) do
        {:found, id} ->
          updated = merge_into(state.entries[id], finding, reviewer)
          %{state | entries: Map.put(state.entries, id, updated)}

        :none ->
          id = state.next_id
          entry = to_merged(finding, reviewer)

          %{
            state
            | buckets: Map.put(state.buckets, key, ids ++ [id]),
              entries: Map.put(state.entries, id, entry),
              next_id: id + 1
          }
      end
    end)
    |> then(fn %{entries: entries} ->
      entries
      |> Enum.sort_by(&elem(&1, 0))
      |> Enum.map(&elem(&1, 1))
    end)
  end

  # --- Sorting & Bucketing ---

  defp flatten_and_sort(by_reviewer) do
    by_reviewer
    |> Enum.flat_map(fn {reviewer, findings} ->
      Enum.map(findings, &{reviewer, &1})
    end)
    |> Enum.sort_by(fn {reviewer, f} ->
      {normalize_file(f.file), norm_key(f.category), f.line, norm_key(f.title), reviewer}
    end)
  end

  defp bucket_key(finding) do
    {normalize_file(finding.file), norm_key(finding.category)}
  end

  defp find_match(ids, finding, entries) do
    Enum.find_value(ids, :none, fn id ->
      if equivalent?(entries[id], finding), do: {:found, id}
    end)
  end

  # --- Equivalence ---

  @doc false
  def equivalent?(existing, candidate) do
    normalize_file(existing.file) == normalize_file(candidate.file) and
      norm_key(existing.category) == norm_key(candidate.category) and
      lines_close?(existing.line, candidate.line) and
      content_match?(existing, candidate)
  end

  defp lines_close?(a, b) when a > 0 and b > 0, do: abs(a - b) <= 3
  defp lines_close?(_, _), do: true

  defp content_match?(existing, candidate) do
    existing_title = norm_key(Map.get(existing, :title, ""))
    candidate_title = norm_key(candidate.title)

    cond do
      existing_title == candidate_title and existing_title != "" ->
        existing_line = Map.get(existing, :line, 0)
        # Same title + different positive lines = different instances
        not (existing_line > 0 and candidate.line > 0 and existing_line != candidate.line)

      true ->
        existing_desc = Map.get(existing, :description, "")
        token_overlap?(existing_title, existing_desc, candidate_title, candidate.description)
    end
  end

  defp token_overlap?(title_a, desc_a, title_b, desc_b) do
    tokens_a = content_tokens(title_a, desc_a)
    tokens_b = content_tokens(title_b, desc_b)
    overlap = MapSet.intersection(tokens_a, tokens_b) |> MapSet.size()
    smaller = min(MapSet.size(tokens_a), MapSet.size(tokens_b))

    overlap >= 2 and (overlap >= 3 or (smaller > 0 and overlap / smaller >= 0.4))
  end

  # --- Tokenization ---

  @doc false
  def content_tokens(a, b), do: content_tokens([a, b])

  @doc false
  def content_tokens(values) when is_list(values) do
    Enum.reduce(values, MapSet.new(), fn val, acc ->
      val
      |> to_string()
      |> String.downcase()
      |> extract_tokens()
      |> Enum.reduce(acc, &MapSet.put(&2, &1))
    end)
  end

  defp extract_tokens(text) do
    ~r/[a-z0-9]+/
    |> Regex.scan(text)
    |> List.flatten()
    |> Enum.flat_map(fn token ->
      if String.length(token) < @min_token_len or MapSet.member?(@stop_words, token) do
        []
      else
        stem(token)
      end
    end)
  end

  defp stem(word) do
    len = String.length(word)

    cond do
      len > 6 and String.ends_with?(word, "ing") ->
        root = String.slice(word, 0, len - 3)
        Enum.uniq([root, word])

      len > 5 and String.ends_with?(word, "ed") ->
        root = String.slice(word, 0, len - 2)
        Enum.uniq([root, root <> "e", word])

      len > 5 and String.ends_with?(word, "es") ->
        root = String.slice(word, 0, len - 2)
        Enum.uniq([root, word])

      len > 5 and String.ends_with?(word, "s") ->
        root = String.slice(word, 0, len - 1)
        Enum.uniq([root, word])

      true ->
        [word]
    end
  end

  # --- Merging ---

  defp to_merged(%Finding{} = f, reviewer) do
    %{
      severity: f.severity,
      category: f.category,
      file: f.file,
      line: f.line,
      title: f.title,
      description: f.description,
      suggestion: f.suggestion,
      evidence: f.evidence,
      reviewers: [reviewer]
    }
  end

  defp merge_into(existing, %Finding{} = candidate, reviewer) do
    %{
      existing
      | severity: worst_severity(existing.severity, candidate.severity),
        line: choose_line(existing.line, candidate.line),
        title: best_text(existing.title, candidate.title),
        description: best_text(existing.description, candidate.description),
        suggestion: best_text(existing[:suggestion], candidate.suggestion),
        evidence: best_text(existing[:evidence], candidate.evidence),
        reviewers: Enum.sort(Enum.uniq([reviewer | existing.reviewers]))
    }
  end

  defp worst_severity(a, b) do
    if Map.get(@severity_order, a, 3) <= Map.get(@severity_order, b, 3), do: a, else: b
  end

  defp choose_line(a, b) do
    positives = Enum.filter([a, b], &(&1 > 0))
    if positives != [], do: Enum.min(positives), else: max(a, max(b, 0))
  end

  defp best_text(nil, b), do: b
  defp best_text(a, nil), do: a
  defp best_text(a, b) when is_binary(a) and is_binary(b) do
    if String.length(b) > String.length(a), do: b, else: a
  end

  # --- Normalization ---

  defp normalize_file(nil), do: ""
  defp normalize_file("N/A"), do: ""
  defp normalize_file(f), do: f

  defp norm_key(nil), do: ""

  defp norm_key(s) when is_binary(s) do
    s |> String.downcase() |> String.trim() |> String.replace(~r/\s+/, " ")
  end
end
