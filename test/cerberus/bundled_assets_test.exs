defmodule Cerberus.BundledAssetsTest do
  use ExUnit.Case, async: true

  test "embeds shipped defaults and review assets" do
    assert {:ok, defaults} = Cerberus.BundledAssets.fetch("defaults/config.yml")
    assert defaults =~ "providers:"
    assert defaults =~ "reviewers:"

    assert {:ok, prompt} = Cerberus.BundledAssets.fetch("pi/agents/correctness.md")
    assert prompt =~ "trace correctness & logic reviewer"

    assert {:ok, template} = Cerberus.BundledAssets.fetch("templates/review-prompt.md")
    assert template =~ "{{DIFF_FILE}}"
  end

  test "does not expose test-only helper files as bundled runtime assets" do
    assert :error == Cerberus.BundledAssets.fetch("test/support/cli_test_support.ex")
  end

  test "review prompt loading falls back to the bundled template" do
    assert {:ok, template} = Cerberus.ReviewPrompt.load_template("/nonexistent/path")
    assert template =~ "{{PERSPECTIVE}}"
  end
end
