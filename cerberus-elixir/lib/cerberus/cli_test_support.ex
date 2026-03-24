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
