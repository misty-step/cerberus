defmodule Cerberus.Verdict do
  @moduledoc """
  Structured verdict from a reviewer.

  Parses LLM review responses (text ending with a ```json block) and validates
  against the Cerberus verdict schema. Mirrors the contract defined in
  `scripts/lib/review_schema.py`.

  ## Parsing

      Cerberus.Verdict.parse(llm_response_text)
      # => {:ok, %Cerberus.Verdict{}} | {:error, reason}
  """

  alias Cerberus.Verdict.Finding

  @enforce_keys [:reviewer, :perspective, :verdict, :confidence, :summary, :findings, :stats]
  defstruct [:reviewer, :perspective, :verdict, :confidence, :summary, :findings, :stats]

  @type t :: %__MODULE__{
          reviewer: String.t(),
          perspective: String.t(),
          verdict: String.t(),
          confidence: float(),
          summary: String.t(),
          findings: [Finding.t()],
          stats: map()
        }

  @valid_verdicts MapSet.new(~w(PASS WARN FAIL SKIP))
  @required_root_keys ~w(reviewer perspective verdict confidence summary findings stats)
  @stats_keys ~w(files_reviewed files_with_issues critical major minor info)

  @doc "Parse LLM response text containing a verdict JSON block."
  @spec parse(String.t()) :: {:ok, t()} | {:error, term()}
  def parse(text) when is_binary(text) do
    with {:ok, json_str} <- extract_json(text),
         {:ok, map} <- Jason.decode(json_str),
         {:ok, verdict} <- validate(map) do
      {:ok, verdict}
    end
  end

  @doc "Validate a decoded JSON map against the verdict schema."
  @spec validate(map()) :: {:ok, t()} | {:error, term()}
  def validate(map) when is_map(map) do
    with :ok <- check_required_keys(map),
         :ok <- check_verdict_value(map),
         :ok <- check_confidence(map),
         :ok <- check_string_fields(map),
         {:ok, findings} <- validate_findings(map["findings"]),
         :ok <- check_stats(map["stats"]) do
      {:ok,
       %__MODULE__{
         reviewer: map["reviewer"],
         perspective: map["perspective"],
         verdict: map["verdict"],
         confidence: normalize_confidence(map["confidence"]),
         summary: map["summary"],
         findings: findings,
         stats: map["stats"]
       }}
    end
  end

  # --- Extraction ---

  defp extract_json(text) do
    case Regex.scan(~r/```json\s*\n(.*?)```/s, text) do
      [] ->
        trimmed = String.trim(text)

        if String.starts_with?(trimmed, "{") or String.starts_with?(trimmed, "[") do
          {:ok, trimmed}
        else
          {:error, :no_json_block}
        end

      matches ->
        [_, json] = List.last(matches)
        {:ok, String.trim(json)}
    end
  end

  # --- Validation ---

  defp check_required_keys(map) do
    missing = Enum.filter(@required_root_keys, &(not Map.has_key?(map, &1)))
    if missing == [], do: :ok, else: {:error, {:missing_root_keys, missing}}
  end

  defp check_verdict_value(%{"verdict" => v}) do
    if MapSet.member?(@valid_verdicts, v), do: :ok, else: {:error, {:invalid_verdict, v}}
  end

  defp check_confidence(%{"confidence" => c}) when is_number(c) do
    n = normalize_confidence(c)
    if n >= 0.0 and n <= 1.0, do: :ok, else: {:error, {:confidence_out_of_range, c}}
  end

  defp check_confidence(_), do: {:error, :confidence_not_number}

  defp check_string_fields(map) do
    Enum.reduce_while(~w(reviewer perspective summary), :ok, fn key, :ok ->
      if is_binary(map[key]),
        do: {:cont, :ok},
        else: {:halt, {:error, {:"#{key}_not_string", map[key]}}}
    end)
  end

  defp validate_findings(findings) when is_list(findings) do
    results = Enum.map(findings, &Finding.validate/1)
    errors = Enum.filter(results, &match?({:error, _}, &1))

    if errors == [] do
      {:ok, Enum.map(results, fn {:ok, f} -> f end)}
    else
      {:error, {:invalid_findings, errors}}
    end
  end

  defp validate_findings(_), do: {:error, :findings_not_list}

  defp check_stats(stats) when is_map(stats) do
    missing = Enum.filter(@stats_keys, &(not Map.has_key?(stats, &1)))

    if missing != [] do
      {:error, {:missing_stats_keys, missing}}
    else
      non_int = Enum.filter(@stats_keys, fn k -> not is_integer(stats[k]) end)
      if non_int == [], do: :ok, else: {:error, {:stats_not_integer, non_int}}
    end
  end

  defp check_stats(_), do: {:error, :stats_not_map}

  # Normalize percentage-style confidence (e.g. 85 or 85.0 → 0.85)
  defp normalize_confidence(c) when is_integer(c) and c > 1 and c <= 100, do: c / 100.0

  defp normalize_confidence(c) when is_float(c) and c > 1.0 and c <= 100.0,
    do: c / 100.0

  defp normalize_confidence(c), do: c
end
