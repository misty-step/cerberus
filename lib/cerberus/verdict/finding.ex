defmodule Cerberus.Verdict.Finding do
  @moduledoc """
  A single code review finding with severity, location, and evidence.

  Invariants:
  - severity is one of: critical, major, minor, info
  - file and line locate the finding in the repository
  - scope, when present, is "diff" or "defaults-change"
  """

  @enforce_keys [:severity, :category, :file, :line, :title, :description]
  defstruct [
    :severity,
    :category,
    :file,
    :line,
    :title,
    :description,
    :suggestion,
    :evidence,
    :scope,
    :suggestion_verified
  ]

  @type t :: %__MODULE__{
          severity: String.t(),
          category: String.t(),
          file: String.t(),
          line: integer(),
          title: String.t(),
          description: String.t(),
          suggestion: String.t() | nil,
          evidence: String.t() | nil,
          scope: String.t() | nil,
          suggestion_verified: boolean() | nil
        }

  @valid_severities MapSet.new(~w(critical major minor info))
  @severity_rank %{"critical" => 0, "major" => 1, "minor" => 2, "info" => 3}
  @valid_scopes MapSet.new(~w(diff defaults-change))
  @required_keys ~w(severity category file line title description)

  @doc "Numeric rank for severity comparison. Lower = more severe."
  @spec severity_rank(String.t()) :: non_neg_integer()
  def severity_rank(severity), do: Map.get(@severity_rank, severity, 3)

  @doc "True if the finding has critical severity."
  @spec critical?(t()) :: boolean()
  def critical?(%__MODULE__{severity: "critical"}), do: true
  def critical?(%__MODULE__{}), do: false

  @spec validate(map()) :: {:ok, t()} | {:error, term()}
  def validate(map) when is_map(map) do
    with :ok <- check_required(map),
         :ok <- check_severity(map),
         :ok <- check_types(map),
         :ok <- check_optional(map) do
      {:ok, to_struct(map)}
    end
  end

  def validate(_), do: {:error, :finding_not_map}

  defp check_required(map) do
    missing = Enum.filter(@required_keys, &(not Map.has_key?(map, &1)))
    if missing == [], do: :ok, else: {:error, {:missing_fields, missing}}
  end

  defp check_severity(%{"severity" => s}) when is_binary(s) do
    if MapSet.member?(@valid_severities, s), do: :ok, else: {:error, {:invalid_severity, s}}
  end

  defp check_severity(_), do: {:error, :severity_not_string}

  defp check_types(map) do
    cond do
      not is_binary(map["category"]) -> {:error, :category_not_string}
      not is_binary(map["file"]) -> {:error, :file_not_string}
      not is_integer(map["line"]) -> {:error, :line_not_integer}
      not is_binary(map["title"]) -> {:error, :title_not_string}
      not is_binary(map["description"]) -> {:error, :description_not_string}
      true -> :ok
    end
  end

  defp check_optional(map) do
    with :ok <- check_scope(map),
         :ok <- check_suggestion(map),
         :ok <- check_evidence(map),
         :ok <- check_suggestion_verified(map) do
      :ok
    end
  end

  defp check_scope(%{"scope" => s}) when is_binary(s) do
    if MapSet.member?(@valid_scopes, s), do: :ok, else: {:error, {:invalid_scope, s}}
  end

  defp check_scope(%{"scope" => s}) when not is_nil(s), do: {:error, :scope_not_string}
  defp check_scope(_), do: :ok

  defp check_suggestion(%{"suggestion" => s}) when not is_binary(s) and not is_nil(s),
    do: {:error, :suggestion_not_string}

  defp check_suggestion(_), do: :ok

  defp check_evidence(%{"evidence" => e}) when not is_binary(e) and not is_nil(e),
    do: {:error, :evidence_not_string}

  defp check_evidence(_), do: :ok

  defp check_suggestion_verified(%{"suggestion_verified" => v})
       when not is_boolean(v) and not is_nil(v),
       do: {:error, :suggestion_verified_not_boolean}

  defp check_suggestion_verified(_), do: :ok

  defp to_struct(map) do
    %__MODULE__{
      severity: map["severity"],
      category: map["category"],
      file: map["file"],
      line: map["line"],
      title: map["title"],
      description: map["description"],
      suggestion: map["suggestion"],
      evidence: map["evidence"],
      scope: map["scope"],
      suggestion_verified: map["suggestion_verified"]
    }
  end
end
