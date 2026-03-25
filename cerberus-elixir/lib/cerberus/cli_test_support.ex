defmodule Cerberus.CLITestSupport do
  @moduledoc false

  @spec call_llm(map()) :: {:ok, map()}
  def call_llm(_params) do
    {:ok,
     %{
       content: """
       {
         "reviewer": "trace",
         "perspective": "correctness",
         "verdict": "PASS",
         "confidence": 0.85,
         "summary": "No issues found.",
         "findings": [],
         "stats": {
           "files_reviewed": 1,
           "files_with_issues": 0,
           "critical": 0,
           "major": 0,
           "minor": 0,
           "info": 0
         }
       }
       """,
       tool_calls: [],
       usage: %{prompt_tokens: 100, completion_tokens: 25}
     }}
  end
end

defmodule Cerberus.TestSupport.LocalReviewRepo do
  @moduledoc false

  def create! do
    root =
      Path.join(
        System.tmp_dir!(),
        "cerberus_local_review_repo_#{System.unique_integer([:positive])}"
      )

    File.mkdir_p!(root)
    git!(root, ["init", "--initial-branch=main"])
    git!(root, ["config", "user.name", "Cerberus Test"])
    git!(root, ["config", "user.email", "cerberus@example.com"])

    base_content = "defmodule Sample do\n  def version, do: :base\nend\n"
    head_content = "defmodule Sample do\n  def version, do: :head\nend\n"
    dirty_content = "defmodule Sample do\n  def version, do: :dirty\nend\n"

    write!(root, "lib/sample.ex", base_content)
    git!(root, ["add", "."])
    git!(root, ["commit", "-m", "base"])
    base_sha = git!(root, ["rev-parse", "HEAD"])

    write!(root, "lib/sample.ex", head_content)
    write!(root, "lib/added.ex", "defmodule Added do\n  def ping, do: :pong\nend\n")
    write!(root, "README.md", "# Sample fixture\n")
    git!(root, ["add", "."])
    git!(root, ["commit", "-m", "head"])

    head_sha = git!(root, ["rev-parse", "HEAD"])
    short_head_sha = git!(root, ["rev-parse", "--short=8", "HEAD"])
    git!(root, ["branch", "feature/ref-range", head_sha])
    git!(root, ["tag", "review-target", head_sha])

    write!(root, "lib/sample.ex", dirty_content)

    %{
      root: root,
      base_sha: base_sha,
      head_sha: head_sha,
      short_head_sha: short_head_sha,
      branch_ref: "feature/ref-range",
      tag_ref: "review-target",
      revision_base_ref: "feature/ref-range^",
      revision_head_ref: "feature/ref-range",
      base_content: base_content,
      head_content: head_content,
      dirty_content: dirty_content
    }
  end

  def cleanup!(%{root: root}) do
    File.rm_rf(root)
    :ok
  end

  def head(repo_root), do: git!(repo_root, ["rev-parse", "HEAD"])
  def status(repo_root), do: git_raw!(repo_root, ["status", "--short"])
  def worktree_list(repo_root), do: git_raw!(repo_root, ["worktree", "list", "--porcelain"])

  def git!(repo_root, args) do
    case System.cmd("git", ["-C", repo_root | args], stderr_to_stdout: true) do
      {output, 0} -> String.trim(output)
      {output, status} -> raise "git #{Enum.join(args, " ")} failed (#{status}): #{output}"
    end
  end

  defp git_raw!(repo_root, args) do
    case System.cmd("git", ["-C", repo_root | args], stderr_to_stdout: true) do
      {output, 0} -> output
      {output, status} -> raise "git #{Enum.join(args, " ")} failed (#{status}): #{output}"
    end
  end

  defp write!(repo_root, relative_path, content) do
    path = Path.join(repo_root, relative_path)
    File.mkdir_p!(Path.dirname(path))
    File.write!(path, content)
    path
  end
end
