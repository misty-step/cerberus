defmodule Cerberus.ReviewPrompt do
  @moduledoc """
  Renders the review user prompt from `templates/review-prompt.md` with PR context.

  Template uses `{{PLACEHOLDER}}` syntax. All placeholders are replaced with
  string values from the PR context map.
  """

  @doc "Render a template string by replacing {{KEY}} placeholders with values from vars."
  @spec render(String.t(), map()) :: String.t()
  def render(template, vars) when is_binary(template) and is_map(vars) do
    Enum.reduce(vars, template, fn {key, val}, acc ->
      String.replace(acc, "{{#{key}}}", to_string(val || ""))
    end)
  end

  @doc "Load the review prompt template from the repo root."
  @spec load_template(String.t()) :: {:ok, String.t()} | {:error, term()}
  def load_template(repo_root) do
    template_path = Path.join(repo_root, "templates/review-prompt.md")

    case File.read(template_path) do
      {:ok, template} ->
        {:ok, template}

      {:error, :enoent} ->
        case Cerberus.BundledAssets.fetch("templates/review-prompt.md") do
          {:ok, template} -> {:ok, template}
          :error -> {:error, :enoent}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc "Build template variables from a PR context map."
  @spec build_vars(map()) :: map()
  def build_vars(pr_context) when is_map(pr_context) do
    %{
      "PR_TITLE" => pr_context[:title] || "",
      "PR_AUTHOR" => pr_context[:author] || "",
      "HEAD_BRANCH" => pr_context[:head_branch] || "",
      "BASE_BRANCH" => pr_context[:base_branch] || "",
      "PR_BODY" => pr_context[:body] || "",
      "DIFF_FILE" => pr_context[:diff_file] || "/tmp/pr.diff",
      "PERSPECTIVE" => pr_context[:perspective] || "",
      "CURRENT_DATE" => Date.utc_today() |> Date.to_iso8601(),
      "PROJECT_CONTEXT_SECTION" => pr_context[:project_context] || ""
    }
  end
end
