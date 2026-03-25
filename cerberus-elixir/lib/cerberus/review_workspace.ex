defmodule Cerberus.ReviewWorkspace do
  @moduledoc false

  defstruct [
    :repo_root,
    :base_ref,
    :head_ref,
    :base_sha,
    :head_sha,
    :diff,
    :diff_file,
    :workspace_root,
    :temp_root,
    no_changes?: false
  ]

  @type t :: %__MODULE__{
          repo_root: String.t(),
          base_ref: String.t(),
          head_ref: String.t(),
          base_sha: String.t(),
          head_sha: String.t(),
          diff: String.t(),
          diff_file: String.t() | nil,
          workspace_root: String.t() | nil,
          temp_root: String.t() | nil,
          no_changes?: boolean()
        }

  @spec prepare(String.t(), String.t(), String.t()) :: {:ok, t()} | {:error, String.t()}
  def prepare(repo_path, base_ref, head_ref) do
    with {:ok, repo_root} <- resolve_repo_root(repo_path),
         {:ok, base_sha} <- resolve_ref(repo_root, "--base", base_ref),
         {:ok, head_sha} <- resolve_ref(repo_root, "--head", head_ref),
         {:ok, diff} <- build_diff(repo_root, base_sha, head_sha) do
      base_workspace = %__MODULE__{
        repo_root: repo_root,
        base_ref: base_ref,
        head_ref: head_ref,
        base_sha: base_sha,
        head_sha: head_sha,
        diff: diff
      }

      if String.trim(diff) == "" do
        {:ok, %{base_workspace | no_changes?: true}}
      else
        materialize_workspace(base_workspace)
      end
    end
  end

  @spec cleanup(t()) :: :ok
  def cleanup(%__MODULE__{temp_root: nil}), do: :ok

  def cleanup(%__MODULE__{temp_root: temp_root}) do
    File.rm_rf(temp_root)
    :ok
  end

  defp resolve_repo_root(repo_path) when repo_path in [nil, ""] do
    {:error, "Missing required --repo option."}
  end

  defp resolve_repo_root(repo_path) do
    expanded = Path.expand(repo_path)

    cond do
      not File.exists?(expanded) ->
        {:error, "Repository path not found for --repo: #{repo_path}"}

      not File.dir?(expanded) ->
        {:error, "Repository path is not a directory for --repo: #{repo_path}"}

      true ->
        case System.cmd("git", ["-C", expanded, "rev-parse", "--show-toplevel"],
               stderr_to_stdout: true
             ) do
          {output, 0} ->
            {:ok, output |> String.trim() |> Path.expand()}

          {_output, _status} ->
            {:error, "--repo is not inside a Git repository: #{repo_path}"}
        end
    end
  end

  defp resolve_ref(_repo_root, flag, ref) when ref in [nil, ""] do
    {:error, "Missing required #{flag} option."}
  end

  defp resolve_ref(repo_root, flag, ref) do
    case System.cmd(
           "git",
           ["-C", repo_root, "rev-parse", "--verify", "#{ref}^{commit}"],
           stderr_to_stdout: true
         ) do
      {output, 0} ->
        {:ok, output |> String.trim() |> String.split("\n") |> hd()}

      {output, _status} ->
        {:error,
         "Could not resolve #{flag} ref #{inspect(ref)} inside #{repo_root}: #{format_git_output(output)}"}
    end
  end

  defp build_diff(repo_root, base_sha, head_sha) do
    case System.cmd(
           "git",
           ["-C", repo_root, "diff", "--no-color", "--no-ext-diff", "#{base_sha}..#{head_sha}"],
           stderr_to_stdout: true
         ) do
      {output, 0} ->
        {:ok, output}

      {output, _status} ->
        {:error,
         "Failed to generate a diff for #{base_sha}..#{head_sha}: #{format_git_output(output)}"}
    end
  end

  defp materialize_workspace(%__MODULE__{} = workspace) do
    temp_root =
      Path.join(
        System.tmp_dir!(),
        "cerberus-review-workspace-#{System.unique_integer([:positive])}"
      )

    archive_path = Path.join(temp_root, "workspace.tar")
    workspace_root = Path.join(temp_root, "workspace")
    diff_file = Path.join(temp_root, "range.diff")

    with :ok <- File.mkdir_p(workspace_root),
         :ok <- write_archive(workspace.repo_root, workspace.head_sha, archive_path),
         :ok <- extract_archive(archive_path, workspace_root),
         :ok <- File.write(diff_file, workspace.diff) do
      {:ok,
       %{
         workspace
         | temp_root: temp_root,
           workspace_root: workspace_root,
           diff_file: diff_file
       }}
    else
      {:error, reason} ->
        File.rm_rf(temp_root)
        {:error, reason}
    end
  end

  defp write_archive(repo_root, head_sha, archive_path) do
    case System.cmd(
           "git",
           ["-C", repo_root, "archive", "--format=tar", "--output", archive_path, head_sha],
           stderr_to_stdout: true
         ) do
      {_output, 0} ->
        :ok

      {output, _status} ->
        {:error,
         "Failed to materialize #{head_sha} from #{repo_root}: #{format_git_output(output)}"}
    end
  end

  defp extract_archive(archive_path, workspace_root) do
    case System.cmd("tar", ["-xf", archive_path, "-C", workspace_root], stderr_to_stdout: true) do
      {_output, 0} ->
        :ok

      {output, _status} ->
        {:error, "Failed to extract review workspace: #{format_git_output(output)}"}
    end
  end

  defp format_git_output(output) do
    output
    |> String.trim()
    |> case do
      "" -> "git returned an unspecified error"
      text -> text
    end
  end
end
