defmodule Cerberus.Verdict.OverrideTest do
  use ExUnit.Case, async: true

  alias Cerberus.Verdict.Override

  @head_sha "abc1234567890def"

  defp valid_comment(opts \\ []) do
    actor = Keyword.get(opts, :actor, "alice")
    sha = Keyword.get(opts, :sha, "abc1234")
    reason = Keyword.get(opts, :reason, "Known limitation, fix next release")

    %{
      "actor" => actor,
      "body" => """
      /cerberus override sha=#{sha}
      reason: #{reason}
      """
    }
  end

  # --- parse/2 ---

  describe "parse/2" do
    test "parses valid override comment" do
      assert {:ok, %Override{actor: "alice", sha: "abc1234"}} =
               Override.parse(valid_comment(), @head_sha)
    end

    test "parses /council override command" do
      comment = %{
        "actor" => "bob",
        "body" => "/council override sha=abc1234\nreason: Legacy alias"
      }

      assert {:ok, %Override{actor: "bob"}} = Override.parse(comment, @head_sha)
    end

    test "extracts reason from body" do
      assert {:ok, %Override{reason: "Known limitation, fix next release"}} =
               Override.parse(valid_comment(), @head_sha)
    end

    test "rejects nil input" do
      assert :error = Override.parse(nil, @head_sha)
    end

    test "rejects empty string" do
      assert :error = Override.parse("", @head_sha)
    end

    test "rejects comment without override command" do
      comment = %{"actor" => "alice", "body" => "LGTM, ship it"}
      assert :error = Override.parse(comment, @head_sha)
    end

    test "rejects SHA shorter than 7 chars" do
      assert :error = Override.parse(valid_comment(sha: "abc12"), @head_sha)
    end

    test "rejects SHA that doesn't prefix head" do
      assert :error = Override.parse(valid_comment(sha: "ffffff1"), @head_sha)
    end

    test "accepts SHA when head_sha is nil (no validation)" do
      assert {:ok, %Override{sha: "abc1234"}} =
               Override.parse(valid_comment(), nil)
    end

    test "falls back to author field" do
      comment = %{
        "author" => "carol",
        "body" => "/cerberus override sha=abc1234\nreason: Test"
      }

      assert {:ok, %Override{actor: "carol"}} = Override.parse(comment, @head_sha)
    end

    test "falls back to non-command lines as reason" do
      comment = %{
        "actor" => "alice",
        "body" => "/cerberus override sha=abc1234\nThis is acceptable risk"
      }

      assert {:ok, %Override{reason: "This is acceptable risk"}} =
               Override.parse(comment, @head_sha)
    end

    test "parses JSON string input" do
      json = Jason.encode!(valid_comment())
      assert {:ok, %Override{actor: "alice"}} = Override.parse(json, @head_sha)
    end
  end

  # --- authorized?/4 ---

  describe "authorized?/4" do
    test "pr_author policy: author can override" do
      assert Override.authorized?("alice", :pr_author, "alice", %{})
    end

    test "pr_author policy: case-insensitive match" do
      assert Override.authorized?("Alice", :pr_author, "alice", %{})
    end

    test "pr_author policy: non-author rejected" do
      refute Override.authorized?("bob", :pr_author, "alice", %{})
    end

    test "write_access policy: write permission accepted" do
      perms = %{"bob" => :write}
      assert Override.authorized?("bob", :write_access, "alice", perms)
    end

    test "write_access policy: triage permission rejected" do
      perms = %{"bob" => :triage}
      refute Override.authorized?("bob", :write_access, "alice", perms)
    end

    test "maintainers_only policy: maintain accepted" do
      perms = %{"carol" => :maintain}
      assert Override.authorized?("carol", :maintainers_only, "alice", perms)
    end

    test "maintainers_only policy: admin accepted" do
      perms = %{"carol" => :admin}
      assert Override.authorized?("carol", :maintainers_only, "alice", perms)
    end

    test "maintainers_only policy: write rejected" do
      perms = %{"bob" => :write}
      refute Override.authorized?("bob", :maintainers_only, "alice", perms)
    end
  end

  # --- select/5 ---

  describe "select/5" do
    test "returns first authorized override" do
      comments = [
        valid_comment(actor: "bob"),
        valid_comment(actor: "alice")
      ]

      assert {:ok, %Override{actor: "alice"}} =
               Override.select(comments, @head_sha, :pr_author, "alice")
    end

    test "skips unauthorized comments" do
      comments = [
        valid_comment(actor: "bob"),
        valid_comment(actor: "carol")
      ]

      assert :none = Override.select(comments, @head_sha, :pr_author, "alice")
    end

    test "returns :none for empty list" do
      assert :none = Override.select([], @head_sha, :pr_author, "alice")
    end
  end

  # --- effective_policy/3 ---

  describe "effective_policy/3" do
    test "returns global policy when no failures" do
      verdicts = [%{verdict: "PASS", reviewer: "trace"}]
      assert :pr_author = Override.effective_policy(verdicts, %{}, :pr_author)
    end

    test "escalates to strictest failing reviewer policy" do
      verdicts = [
        %{verdict: "FAIL", reviewer: "trace"},
        %{verdict: "FAIL", reviewer: "guard"}
      ]

      reviewer_policies = %{
        "trace" => :pr_author,
        "guard" => :maintainers_only
      }

      assert :maintainers_only =
               Override.effective_policy(verdicts, reviewer_policies, :pr_author)
    end

    test "uses global policy for reviewers without explicit policy" do
      verdicts = [%{verdict: "FAIL", reviewer: "craft"}]
      assert :write_access = Override.effective_policy(verdicts, %{}, :write_access)
    end
  end
end
