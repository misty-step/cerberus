defmodule Cerberus.Verdict.Override do
  @moduledoc """
  Override parsing, SHA validation, and policy-based authorization.

  Overrides let authorized actors bypass verdict gates on specific commits.

  Invariants:
  - SHA must be >= 7 hex chars and must prefix the HEAD SHA
  - Reason is required
  - Policy determines who can override: pr_author < write_access < maintainers_only
  """

  @enforce_keys [:actor, :sha, :reason]
  defstruct [:actor, :sha, :reason]

  @type t :: %__MODULE__{
          actor: String.t(),
          sha: String.t(),
          reason: String.t()
        }

  @type policy :: :pr_author | :write_access | :maintainers_only
  @type permission :: :pull | :triage | :write | :maintain | :admin

  @policy_strictness %{pr_author: 0, write_access: 1, maintainers_only: 2}
  @sha_re ~r/sha=([0-9a-fA-F]+)/
  @command_re ~r{/cerberus\s+override|/council\s+override}

  # --- Parsing ---

  @spec parse(map() | String.t() | nil, String.t() | nil) :: {:ok, t()} | :error
  def parse(nil, _), do: :error
  def parse("", _), do: :error
  def parse("null", _), do: :error

  def parse(raw, head_sha) when is_binary(raw) do
    case Jason.decode(raw) do
      {:ok, map} -> parse(map, head_sha)
      {:error, _} -> :error
    end
  end

  def parse(map, head_sha) when is_map(map) do
    body = map["body"] || ""

    if Regex.match?(@command_re, body) do
      with {:ok, sha} <- validate_sha(body, head_sha),
           {:ok, reason} <- extract_reason(body) do
        actor = map["actor"] || map["author"] || "unknown"
        {:ok, %__MODULE__{actor: actor, sha: sha, reason: reason}}
      end
    else
      :error
    end
  end

  def parse(_, _), do: :error

  # --- Selection ---

  @spec select([map()], String.t(), policy(), String.t(), map()) :: {:ok, t()} | :none
  def select(comments, head_sha, policy, pr_author, permissions \\ %{}) do
    Enum.find_value(comments, :none, fn comment ->
      with {:ok, override} <- parse(comment, head_sha),
           true <- authorized?(override.actor, policy, pr_author, permissions) do
        {:ok, override}
      else
        _ -> nil
      end
    end)
  end

  # --- Authorization ---

  @spec authorized?(String.t(), policy(), String.t() | nil, map()) :: boolean()
  def authorized?(actor, :pr_author, pr_author, _perms) do
    is_binary(pr_author) and String.downcase(actor) == String.downcase(pr_author)
  end

  def authorized?(actor, :write_access, _pr_author, perms) do
    Map.get(perms, actor) in [:write, :maintain, :admin]
  end

  def authorized?(actor, :maintainers_only, _pr_author, perms) do
    Map.get(perms, actor) in [:maintain, :admin]
  end

  def authorized?(_, _, _, _), do: false

  # --- Effective Policy ---

  @spec effective_policy([map()], map(), policy()) :: policy()
  def effective_policy(verdicts, reviewer_policies, global_policy) do
    verdicts
    |> Enum.filter(&(&1.verdict == "FAIL"))
    |> Enum.reduce(global_policy, fn v, strictest ->
      reviewer_policy = Map.get(reviewer_policies, v.reviewer, global_policy)

      if strictness(reviewer_policy) > strictness(strictest),
        do: reviewer_policy,
        else: strictest
    end)
  end

  defp strictness(policy), do: Map.get(@policy_strictness, policy, -1)

  defp validate_sha(body, head_sha) do
    case Regex.run(@sha_re, body) do
      [_, sha] when byte_size(sha) >= 7 ->
        if is_nil(head_sha) or String.starts_with?(head_sha, sha),
          do: {:ok, sha},
          else: :error

      _ ->
        :error
    end
  end

  defp extract_reason(body) do
    lines = String.split(body, "\n", trim: true)

    reason =
      Enum.find_value(lines, fn line ->
        trimmed = String.trim(line)

        if String.match?(trimmed, ~r/^reason:\s*/i) do
          trimmed |> String.replace(~r/^reason:\s*/i, "") |> String.trim()
        end
      end)

    # Fallback: join non-command, non-empty lines
    reason =
      reason ||
        lines
        |> Enum.reject(&Regex.match?(@command_re, &1))
        |> Enum.map(&String.trim/1)
        |> Enum.reject(&(&1 == ""))
        |> Enum.join(" ")

    if reason == "", do: :error, else: {:ok, reason}
  end
end
