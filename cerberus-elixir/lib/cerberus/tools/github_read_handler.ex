defmodule Cerberus.Tools.GithubReadHandler do
  @moduledoc """
  Dispatches github_read tool calls to `Cerberus.GitHub` API functions.

  `build/3` returns a closure bound to a specific repo and ref, matching the
  tool handler contract: `(%{name, arguments}) -> {:ok, text} | {:error, text}`.
  """

  alias Cerberus.GitHub

  @doc "Build a tool handler closure for the given repo and ref."
  @spec build(String.t(), String.t(), keyword()) :: (map() -> {:ok, String.t()} | {:error, String.t()})
  def build(repo, ref, github_opts) do
    fn call -> dispatch(call, repo, ref, github_opts) end
  end

  defp dispatch(%{name: "get_file_contents", arguments: args}, repo, ref, opts) do
    path = args["path"] || ""

    case GitHub.get_file_contents(repo, path, ref, opts) do
      {:ok, content} -> {:ok, slice_lines(content, args["start_line"], args["end_line"])}
      {:error, reason} -> {:error, format_error(reason)}
    end
  end

  defp dispatch(%{name: "search_code", arguments: args}, repo, _ref, opts) do
    query = args["query"] || ""
    search_opts = if args["path_filter"], do: Keyword.put(opts, :path_filter, args["path_filter"]), else: opts

    case GitHub.search_code(repo, query, search_opts) do
      {:ok, []} -> {:ok, "No results found for: #{query}"}
      {:ok, items} -> {:ok, format_search_results(items)}
      {:error, reason} -> {:error, format_error(reason)}
    end
  end

  defp dispatch(%{name: "list_directory", arguments: args}, repo, ref, opts) do
    path = args["path"] || ""

    case GitHub.list_directory(repo, path, ref, opts) do
      {:ok, entries} -> {:ok, format_directory(entries)}
      {:error, reason} -> {:error, format_error(reason)}
    end
  end

  defp dispatch(%{name: name}, _repo, _ref, _opts) do
    {:error, "Unknown tool: #{name}"}
  end

  # --- Formatting ---

  defp slice_lines(content, nil, nil), do: content

  defp slice_lines(content, start_line, end_line) do
    lines = String.split(content, "\n")
    s = to_int(start_line, 1)
    e = to_int(end_line, length(lines))
    start_idx = max(s - 1, 0)
    end_idx = e - 1

    case lines |> Enum.slice(start_idx..end_idx//1) |> Enum.join("\n") do
      "" when content != "" -> "(no content in lines #{s}..#{e})"
      result -> result
    end
  end

  defp to_int(n, _default) when is_integer(n), do: n

  defp to_int(s, default) when is_binary(s) do
    case Integer.parse(s) do
      {n, _} -> n
      :error -> default
    end
  end

  defp to_int(_, default), do: default

  defp format_search_results(items) do
    items
    |> Enum.map(fn item ->
      path = item["path"] || item["name"] || "?"
      fragments = (get_in(item, ["text_matches", Access.all(), "fragment"]) || []) |> Enum.reject(&is_nil/1)
      frag_text = if fragments == [], do: "", else: "\n  " <> Enum.join(fragments, "\n  ")
      "#{path}#{frag_text}"
    end)
    |> Enum.join("\n")
  end

  defp format_directory(entries) do
    entries
    |> Enum.map(fn e ->
      type = if e["type"] == "dir", do: "/", else: ""
      "#{e["name"]}#{type}"
    end)
    |> Enum.join("\n")
  end

  defp format_error({:http_error, status, _body}), do: "GitHub API error: #{status}"
  defp format_error({:transient, msg}), do: "GitHub API temporarily unavailable: #{msg}"
  defp format_error({:auth, msg}), do: "Authentication failed: #{msg}"
  defp format_error({:permissions, msg}), do: "Insufficient permissions: #{msg}"
  defp format_error({:invalid_path, path}), do: "Invalid path (traversal or absolute): #{path}"
  defp format_error({:decode_error, path}), do: "Failed to decode file content: #{path}"
  defp format_error({:unexpected_response, path}), do: "Unexpected API response for: #{path}"
  defp format_error({:file_too_large, path, size}), do: "File too large for contents API (#{size} bytes): #{path}"
  defp format_error({:not_a_file, path}), do: "Path is a directory, not a file: #{path}"
  defp format_error({:not_a_directory, path}), do: "Path is a file, not a directory: #{path}"
  defp format_error(other), do: "Error: #{inspect(other)}"
end
