defmodule Cerberus.Tools.LocalRepoReadHandler do
  @moduledoc """
  Local filesystem implementation of the read-only review tools.

  Reviewers use the same tool contract as the GitHub-backed path, but the CLI
  resolves reads, searches, and directory listings from the current working
  tree instead of the GitHub API.
  """

  @search_limit "20"
  @max_symlink_hops 40

  @doc "Build a tool handler closure rooted at the local repository."
  @spec build(String.t(), keyword()) :: (map() -> {:ok, String.t()} | {:error, String.t()})
  def build(repo_root, opts \\ []) do
    context = %{
      repo_root: Path.expand(repo_root),
      executables: %{
        rg: Keyword.get(opts, :rg, System.find_executable("rg")),
        grep: Keyword.get(opts, :grep, System.find_executable("grep"))
      }
    }

    fn call -> dispatch(call, context) end
  end

  defp dispatch(%{name: "get_file_contents", arguments: args}, context) do
    path = args["path"] || ""

    with {:ok, resolved} <- resolve_path(context.repo_root, path),
         true <- File.regular?(resolved) or {:error, {:not_a_file, path}},
         {:ok, content} <- File.read(resolved) do
      {:ok, slice_lines(content, args["start_line"], args["end_line"])}
    else
      {:error, reason} -> {:error, format_error(reason)}
    end
  end

  defp dispatch(%{name: "search_code", arguments: args}, context) do
    query = args["query"] || ""

    cond do
      query == "" ->
        {:error, "Error: empty query"}

      executable = context.executables.rg ->
        run_ripgrep(executable, context.repo_root, query, args["path_filter"])

      executable = context.executables.grep ->
        run_grep(executable, context.repo_root, query, args["path_filter"])

      true ->
        {:error, "Error: rg or grep is not available in this runtime"}
    end
  end

  defp dispatch(%{name: "list_directory", arguments: args}, context) do
    path = args["path"] || ""

    with {:ok, resolved} <- resolve_directory(context.repo_root, path),
         {:ok, entries} <- File.ls(resolved) do
      {:ok,
       entries
       |> Enum.sort()
       |> Enum.map_join("\n", fn entry ->
         suffix = if File.dir?(Path.join(resolved, entry)), do: "/", else: ""
         "#{entry}#{suffix}"
       end)}
    else
      {:error, reason} -> {:error, format_error(reason)}
    end
  end

  defp dispatch(%{name: name}, _context) do
    {:error, "Unknown tool: #{name}"}
  end

  defp run_ripgrep(executable, repo_root, query, path_filter) do
    args =
      [
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--max-count",
        @search_limit
      ]
      |> maybe_put_glob(path_filter)
      |> Kernel.++(["--", query, "."])

    case System.cmd(executable, args, cd: repo_root, stderr_to_stdout: true) do
      {"", 1} -> {:ok, "No results found for: #{query}"}
      {output, 0} -> {:ok, String.trim_trailing(output)}
      {output, _status} -> {:error, "Error: #{String.trim(output)}"}
    end
  end

  defp run_grep(executable, repo_root, query, path_filter) do
    args =
      [
        "-r",
        "-n",
        "-m",
        @search_limit
      ]
      |> maybe_put_include(path_filter)
      |> Kernel.++(["--", query, "."])

    case System.cmd(executable, args, cd: repo_root, stderr_to_stdout: true) do
      {"", 1} -> {:ok, "No results found for: #{query}"}
      {output, 0} -> {:ok, String.trim_trailing(output)}
      {output, _status} -> {:error, "Error: #{String.trim(output)}"}
    end
  end

  defp maybe_put_glob(args, nil), do: args
  defp maybe_put_glob(args, ""), do: args
  defp maybe_put_glob(args, glob), do: args ++ ["--glob", glob]

  defp maybe_put_include(args, nil), do: args
  defp maybe_put_include(args, ""), do: args
  defp maybe_put_include(args, glob), do: args ++ ["--include", glob]

  defp resolve_directory(repo_root, ""), do: {:ok, repo_root}

  defp resolve_directory(repo_root, path) do
    with {:ok, resolved} <- resolve_path(repo_root, path),
         true <- File.dir?(resolved) or {:error, {:not_a_directory, path}} do
      {:ok, resolved}
    else
      {:error, reason} -> {:error, reason}
    end
  end

  defp resolve_path(repo_root, path) when is_binary(path) do
    cond do
      path == "" ->
        {:error, {:invalid_path, path}}

      Path.type(path) == :absolute ->
        {:error, {:invalid_path, path}}

      true ->
        expanded = Path.expand(path, repo_root)

        if within_repo_root?(expanded, repo_root) do
          case resolve_existing_path(repo_root, expanded) do
            {:ok, resolved} -> {:ok, resolved}
            {:error, :enoent} -> {:error, {:enoent, path}}
            {:error, :invalid_path} -> {:error, {:invalid_path, path}}
            {:error, reason} -> {:error, {reason, path}}
          end
        else
          {:error, {:invalid_path, path}}
        end
    end
  end

  defp resolve_path(_repo_root, path), do: {:error, {:invalid_path, inspect(path)}}

  defp resolve_existing_path(repo_root, candidate, hops \\ 0)

  defp resolve_existing_path(_repo_root, _candidate, hops) when hops > @max_symlink_hops do
    {:error, :eloop}
  end

  defp resolve_existing_path(repo_root, candidate, hops) do
    if within_repo_root?(candidate, repo_root) do
      candidate
      |> Path.relative_to(repo_root)
      |> Path.split()
      |> walk_segments(repo_root, repo_root, hops)
    else
      {:error, :invalid_path}
    end
  end

  defp walk_segments([], _repo_root, current, _hops), do: {:ok, current}

  defp walk_segments([segment | rest], repo_root, current, hops) do
    next = Path.join(current, segment)

    case File.lstat(next) do
      {:ok, %File.Stat{type: :symlink}} ->
        with {:ok, link} <- File.read_link(next) do
          target = Path.expand(link, Path.dirname(next))
          remainder = Enum.join(rest, "/")
          resolve_existing_path(repo_root, Path.join(target, remainder), hops + 1)
        end

      {:ok, _stat} ->
        walk_segments(rest, repo_root, next, hops)

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp within_repo_root?(resolved, repo_root) do
    resolved == repo_root or String.starts_with?(resolved, repo_root <> "/")
  end

  defp slice_lines(content, nil, nil), do: content

  defp slice_lines(content, start_line, end_line) do
    lines = String.split(content, "\n")
    start_idx = max(to_int(start_line, 1) - 1, 0)
    end_idx = max(to_int(end_line, length(lines)) - 1, start_idx)

    case lines |> Enum.slice(start_idx..end_idx//1) |> Enum.join("\n") do
      "" when content != "" -> "(no content in requested line range)"
      result -> result
    end
  end

  defp to_int(value, _default) when is_integer(value), do: value

  defp to_int(value, default) when is_binary(value) do
    case Integer.parse(value) do
      {parsed, _rest} -> parsed
      :error -> default
    end
  end

  defp to_int(_value, default), do: default

  defp format_error({:invalid_path, path}), do: "Invalid path (traversal or absolute): #{path}"
  defp format_error({:not_a_file, path}), do: "Path is a directory, not a file: #{path}"
  defp format_error({:not_a_directory, path}), do: "Path is a file, not a directory: #{path}"
  defp format_error({:enoent, path}), do: "Path not found: #{path}"
  defp format_error({reason, path}), do: "Error reading #{path}: #{:file.format_error(reason)}"
  defp format_error(other), do: "Error: #{inspect(other)}"
end
