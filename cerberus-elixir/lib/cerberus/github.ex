defmodule Cerberus.GitHub do
  @moduledoc """
  GitHub REST API client for Cerberus review operations.

  Stateless HTTP functions using Req. All functions accept an `opts` keyword
  list supporting `:req` (pre-configured `Req.Request`) for dependency injection.

  ## Error taxonomy

      {:error, {:transient, msg}}    — 429, 5xx, timeout (retried then failed)
      {:error, {:auth, msg}}         — 401
      {:error, {:permissions, msg}}  — 403
      {:error, {:http_error, status, body}}  — other HTTP errors
  """

  @api_url "https://api.github.com"
  @default_max_retries 3
  @max_inline_comments 30
  @override_pattern ~r|/cerberus\s+override\s+sha=([a-f0-9]{7,40})|

  # --- Req construction (DI seam) ---

  defp build_req(opts) do
    case Keyword.get(opts, :req) do
      %Req.Request{} = req -> req
      nil -> default_req()
    end
  end

  defp default_req do
    token =
      System.get_env("GITHUB_TOKEN") || System.get_env("GH_TOKEN") ||
        raise "No GitHub token in GITHUB_TOKEN or GH_TOKEN"

    Req.new(
      base_url: @api_url,
      headers: [
        {"accept", "application/vnd.github+json"},
        {"authorization", "Bearer #{token}"},
        {"x-github-api-version", "2022-11-28"}
      ],
      receive_timeout: 20_000
    )
  end

  # --- Retry logic ---

  defp request_with_retry(method, req, req_opts, opts) do
    max = Keyword.get(opts, :max_retries, @default_max_retries)
    delay_fn = Keyword.get(opts, :retry_delay, &default_delay/1)
    # Disable Req's built-in retry — we own the retry loop and error classification.
    req_opts = Keyword.put(req_opts, :retry, false)
    do_request(method, req, req_opts, 0, max, delay_fn)
  end

  defp default_delay(attempt) do
    ms = trunc(1_000 * :math.pow(2, attempt) + :rand.uniform(500))
    Process.sleep(ms)
  end

  defp do_request(method, req, req_opts, attempt, max, delay_fn) do
    case classify(apply(Req, method, [req, req_opts])) do
      {:ok, resp} ->
        {:ok, resp}

      {:retry, _resp} when attempt < max ->
        delay_fn.(attempt)
        do_request(method, req, req_opts, attempt + 1, max, delay_fn)

      {:retry, resp} ->
        status = Map.get(resp, :status, 0)
        {:error, {:transient, "GitHub API #{status} after #{max} retries"}}

      {:auth, resp} ->
        {:error, {:auth, "Authentication failed (#{resp.status})"}}

      {:permissions, resp} ->
        {:error, {:permissions, "Insufficient permissions (#{resp.status})"}}

      {:http_error, status, body} ->
        {:error, {:http_error, status, body}}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp classify({:ok, %{status: s} = r}) when s in 200..299, do: {:ok, r}
  defp classify({:ok, %{status: 401} = r}), do: {:auth, r}
  defp classify({:ok, %{status: 403} = r}), do: {:permissions, r}
  defp classify({:ok, %{status: s} = r}) when s in [429, 500, 502, 503, 504], do: {:retry, r}
  defp classify({:ok, %{status: s, body: b}}), do: {:http_error, s, b}
  defp classify({:error, %{reason: :timeout}}), do: {:retry, %{status: 0}}
  defp classify({:error, reason}), do: {:error, reason}

  # --- Pagination ---

  defp fetch_pages(req, path, per_page, max_pages, opts, page \\ 1, acc \\ []) do
    case request_with_retry(
           :get,
           req,
           [url: path, params: [per_page: per_page, page: page]],
           opts
         ) do
      {:ok, %{body: items}} when is_list(items) ->
        all = acc ++ items

        if length(items) < per_page or page >= max_pages,
          do: {:ok, all},
          else: fetch_pages(req, path, per_page, max_pages, opts, page + 1, all)

      {:ok, _} ->
        {:ok, acc}

      error ->
        error
    end
  end

  # === Public API ===

  @doc "Fetch PR metadata: title, author, head/base refs, body, head SHA."
  def fetch_pr_context(repo, pr_number, opts \\ []) do
    req = build_req(opts)

    case request_with_retry(:get, req, [url: "/repos/#{repo}/pulls/#{pr_number}"], opts) do
      {:ok, %{body: b}} ->
        {:ok,
         %{
           title: b["title"],
           author: get_in(b, ["user", "login"]),
           head_ref: get_in(b, ["head", "ref"]),
           base_ref: get_in(b, ["base", "ref"]),
           head_sha: get_in(b, ["head", "sha"]),
           body: b["body"]
         }}

      error ->
        error
    end
  end

  @doc "Fetch raw PR diff."
  def fetch_pr_diff(repo, pr_number, opts \\ []) do
    req = build_req(opts) |> Req.merge(headers: [{"accept", "application/vnd.github.diff"}])

    case request_with_retry(:get, req, [url: "/repos/#{repo}/pulls/#{pr_number}"], opts) do
      {:ok, %{body: body}} when is_binary(body) -> {:ok, body}
      {:ok, %{body: body}} -> {:ok, to_string(body)}
      error -> error
    end
  end

  @doc "Fetch PR/issue comments with pagination."
  def fetch_comments(repo, pr_number, opts \\ []) do
    req = build_req(opts)
    per_page = Keyword.get(opts, :per_page, 100)
    max_pages = Keyword.get(opts, :max_pages, 20)
    fetch_pages(req, "/repos/#{repo}/issues/#{pr_number}/comments", per_page, max_pages, opts)
  end

  @doc "Find comment ID by HTML marker in body. Pure function."
  def find_comment_by_marker(comments, marker) when is_list(comments) do
    Enum.find_value(comments, fn c ->
      if String.contains?(c["body"] || "", marker), do: c["id"]
    end)
  end

  @doc "Upsert PR comment idempotently via HTML marker."
  def upsert_comment(repo, pr_number, marker, body, opts \\ []) do
    req = build_req(opts)

    with {:ok, comments} <- fetch_comments(repo, pr_number, opts) do
      case find_comment_by_marker(comments, marker) do
        nil ->
          request_with_retry(
            :post,
            req,
            [url: "/repos/#{repo}/issues/#{pr_number}/comments", json: %{body: body}],
            opts
          )

        id ->
          request_with_retry(
            :patch,
            req,
            [url: "/repos/#{repo}/issues/comments/#{id}", json: %{body: body}],
            opts
          )
      end
    end
  end

  @doc "List all PR reviews with pagination."
  def list_pr_reviews(repo, pr_number, opts \\ []) do
    req = build_req(opts)
    fetch_pages(req, "/repos/#{repo}/pulls/#{pr_number}/reviews", 100, 10, opts)
  end

  @doc "List changed files in a PR with patch data."
  def list_pr_files(repo, pr_number, opts \\ []) do
    req = build_req(opts)
    fetch_pages(req, "/repos/#{repo}/pulls/#{pr_number}/files", 100, 10, opts)
  end

  @doc """
  Create a PR review with inline comments.

  `comments` is a list of `%{path: String.t(), position: pos_integer(), body: String.t()}`.
  Capped at #{@max_inline_comments} inline comments.
  """
  def create_pr_review(repo, pr_number, commit_id, body, comments, opts \\ []) do
    req = build_req(opts)

    payload = %{
      commit_id: commit_id,
      body: body,
      event: "COMMENT",
      comments: Enum.take(comments, @max_inline_comments)
    }

    request_with_retry(
      :post,
      req,
      [url: "/repos/#{repo}/pulls/#{pr_number}/reviews", json: payload],
      opts
    )
  end

  @doc "Create a GitHub check run."
  def create_check_run(repo, head_sha, name, opts \\ []) do
    req = build_req(opts)

    payload = %{
      name: name,
      head_sha: head_sha,
      status: Keyword.get(opts, :status, "queued")
    }

    request_with_retry(:post, req, [url: "/repos/#{repo}/check-runs", json: payload], opts)
  end

  @doc "Update a GitHub check run status/conclusion."
  def update_check_run(repo, check_run_id, attrs, opts \\ []) do
    req = build_req(opts)

    request_with_retry(
      :patch,
      req,
      [url: "/repos/#{repo}/check-runs/#{check_run_id}", json: attrs],
      opts
    )
  end

  @doc """
  Parse `/cerberus override sha=<sha>` commands from PR comments.

  Returns `[%{sha: String.t(), actor: String.t(), comment_id: integer()}]`.
  """
  def fetch_override_comments(repo, pr_number, opts \\ []) do
    with {:ok, comments} <- fetch_comments(repo, pr_number, opts) do
      overrides =
        Enum.flat_map(comments, fn c ->
          body = c["body"] || ""
          actor = get_in(c, ["user", "login"]) || "unknown"

          case Regex.run(@override_pattern, body) do
            [_, sha] -> [%{sha: sha, actor: actor, comment_id: c["id"]}]
            _ -> []
          end
        end)

      {:ok, overrides}
    end
  end

  @doc """
  Build a map of new-file line number → diff position from a patch string.

  Used to anchor inline review comments at the correct diff position.
  """
  def build_position_map(patch) when is_binary(patch) do
    patch
    |> String.split("\n")
    |> Enum.reduce({%{}, 0, 0}, fn line, {map, pos, ln} ->
      cond do
        String.starts_with?(line, "@@") ->
          case Regex.run(~r/\+(\d+)/, line) do
            [_, start] -> {map, pos + 1, String.to_integer(start)}
            _ -> {map, pos + 1, ln}
          end

        String.starts_with?(line, "-") ->
          {map, pos + 1, ln}

        String.starts_with?(line, "+") ->
          {Map.put(map, ln, pos + 1), pos + 1, ln + 1}

        true ->
          {Map.put(map, ln, pos + 1), pos + 1, ln + 1}
      end
    end)
    |> elem(0)
  end

  def build_position_map(_), do: %{}

  # === Repository content API ===

  @doc "Fetch file contents from a repo at a given ref. Returns decoded text."
  def get_file_contents(repo, path, ref, opts \\ []) do
    with :ok <- validate_path(path) do
      req = build_req(opts)
      params = if ref, do: [ref: ref], else: []

      case request_with_retry(
             :get,
             req,
             [url: "/repos/#{repo}/contents/#{path}", params: params],
             opts
           ) do
        {:ok, %{body: items}} when is_list(items) ->
          {:error, {:not_a_file, path}}

        {:ok, %{body: %{"content" => content, "encoding" => "base64"}}} when is_binary(content) ->
          case Base.decode64(content, ignore: :whitespace) do
            {:ok, decoded} -> {:ok, decoded}
            :error -> {:error, {:decode_error, path}}
          end

        {:ok, %{body: %{"content" => content}}} when is_binary(content) ->
          {:ok, content}

        {:ok, %{body: %{"type" => "file", "size" => size}}} ->
          {:error, {:file_too_large, path, size}}

        {:ok, _} ->
          {:error, {:unexpected_response, path}}

        error ->
          error
      end
    end
  end

  @doc "Search code in a repository. Returns list of matching items."
  def search_code(repo, query, opts \\ []) do
    req =
      build_req(opts)
      |> Req.merge(headers: [{"accept", "application/vnd.github.text-match+json"}])

    path_filter = Keyword.get(opts, :path_filter)

    sanitized = String.replace(query, ~r/(repo|org|user|fork):\S+/i, "")

    safe_filter =
      if path_filter,
        do: String.replace(path_filter, ~r/(repo|org|user|fork):\S+/i, ""),
        else: nil

    q =
      "#{sanitized} repo:#{repo}" <>
        if(safe_filter, do: " path:#{safe_filter}", else: "")

    case request_with_retry(:get, req, [url: "/search/code", params: [q: q]], opts) do
      {:ok, %{body: %{"items" => items}}} -> {:ok, items}
      error -> error
    end
  end

  @doc "List directory contents at a given ref. Returns list of entries."
  def list_directory(repo, path, ref, opts \\ []) do
    with :ok <- validate_path(path) do
      req = build_req(opts)
      params = if ref, do: [ref: ref], else: []

      case request_with_retry(
             :get,
             req,
             [url: "/repos/#{repo}/contents/#{path}", params: params],
             opts
           ) do
        {:ok, %{body: items}} when is_list(items) ->
          {:ok, items}

        {:ok, %{body: %{"type" => "file"}}} ->
          {:error, {:not_a_directory, path}}

        error ->
          error
      end
    end
  end

  # --- Path validation ---

  defp validate_path(path) do
    decoded = URI.decode(path)

    cond do
      String.contains?(decoded, "..") -> {:error, {:invalid_path, path}}
      String.starts_with?(decoded, "/") -> {:error, {:invalid_path, path}}
      true -> :ok
    end
  end
end
