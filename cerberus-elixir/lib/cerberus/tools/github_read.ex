defmodule Cerberus.Tools.GithubRead do
  @moduledoc """
  OpenAI function-calling tool definitions for read-only GitHub repository access.

  These definitions are sent with the LLM request so the model can request
  file contents, search code, and list directories during review.
  """

  @doc "Return tool definitions in OpenAI function-calling format."
  @spec definitions() :: [map()]
  def definitions do
    [
      %{
        "type" => "function",
        "function" => %{
          "name" => "get_file_contents",
          "description" =>
            "Read file contents from the repository. Returns text between optional line bounds.",
          "parameters" => %{
            "type" => "object",
            "properties" => %{
              "path" => %{"type" => "string", "description" => "Repository-relative file path"},
              "start_line" => %{
                "type" => "integer",
                "description" => "Start line (1-indexed, inclusive)"
              },
              "end_line" => %{"type" => "integer", "description" => "End line (inclusive)"}
            },
            "required" => ["path"]
          }
        }
      },
      %{
        "type" => "function",
        "function" => %{
          "name" => "search_code",
          "description" =>
            "Search repository code for a pattern. Returns matching file paths and line numbers.",
          "parameters" => %{
            "type" => "object",
            "properties" => %{
              "query" => %{
                "type" => "string",
                "description" => "Search pattern (regex supported)"
              },
              "path_filter" => %{
                "type" => "string",
                "description" => "Glob pattern to restrict search scope"
              }
            },
            "required" => ["query"]
          }
        }
      },
      %{
        "type" => "function",
        "function" => %{
          "name" => "list_directory",
          "description" => "List files and subdirectories at a repository path.",
          "parameters" => %{
            "type" => "object",
            "properties" => %{
              "path" => %{
                "type" => "string",
                "description" => "Repository-relative directory path"
              }
            },
            "required" => ["path"]
          }
        }
      }
    ]
  end
end
