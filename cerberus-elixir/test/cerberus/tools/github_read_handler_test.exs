defmodule Cerberus.Tools.GithubReadHandlerTest do
  use ExUnit.Case, async: true

  alias Cerberus.Tools.GithubReadHandler

  @repo "owner/repo"
  @ref "abc123"

  defp mock_req(handler) do
    Req.new(
      base_url: "https://api.github.com",
      adapter: fn request ->
        resp = handler.(request.method, request.url.path, request)
        {request, resp}
      end
    )
  end

  defp json_resp(body, status \\ 200), do: Req.Response.new(status: status, body: body)

  defp gh_opts(req), do: [req: req, max_retries: 0, retry_delay: fn _ -> :ok end]

  # --- build/3 ---

  describe "build/3" do
    test "returns a function" do
      handler = GithubReadHandler.build(@repo, @ref, [])
      assert is_function(handler, 1)
    end
  end

  # --- get_file_contents dispatch ---

  describe "get_file_contents" do
    test "returns file content" do
      content = Base.encode64("hello world\n")

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib/foo.ex", _req ->
          json_resp(%{"content" => content, "encoding" => "base64", "type" => "file"})
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))

      assert {:ok, text} =
               handler.(%{name: "get_file_contents", arguments: %{"path" => "lib/foo.ex"}})

      assert text == "hello world\n"
    end

    test "slices lines with start_line and end_line" do
      lines = "line1\nline2\nline3\nline4\nline5\n"
      content = Base.encode64(lines)

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib/foo.ex", _req ->
          json_resp(%{"content" => content, "encoding" => "base64", "type" => "file"})
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))

      assert {:ok, text} =
               handler.(%{
                 name: "get_file_contents",
                 arguments: %{"path" => "lib/foo.ex", "start_line" => 2, "end_line" => 4}
               })

      assert text == "line2\nline3\nline4"
    end

    test "returns error on 404" do
      req =
        mock_req(fn :get, "/repos/owner/repo/contents/missing.ex", _req ->
          json_resp(%{"message" => "Not Found"}, 404)
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))

      assert {:error, msg} =
               handler.(%{name: "get_file_contents", arguments: %{"path" => "missing.ex"}})

      assert is_binary(msg)
      assert msg =~ "404"
    end

    test "returns error when path is a directory" do
      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib", _req ->
          json_resp([%{"name" => "foo.ex", "type" => "file"}])
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))
      assert {:error, msg} = handler.(%{name: "get_file_contents", arguments: %{"path" => "lib"}})
      assert msg =~ "directory"
    end

    test "coerces string line bounds to integers" do
      lines = "line1\nline2\nline3\nline4\nline5\n"
      content = Base.encode64(lines)

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib/foo.ex", _req ->
          json_resp(%{"content" => content, "encoding" => "base64", "type" => "file"})
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))

      assert {:ok, text} =
               handler.(%{
                 name: "get_file_contents",
                 arguments: %{"path" => "lib/foo.ex", "start_line" => "2", "end_line" => "3"}
               })

      assert text == "line2\nline3"
    end

    test "rejects path traversal" do
      handler = GithubReadHandler.build(@repo, @ref, [])

      assert {:error, msg} =
               handler.(%{name: "get_file_contents", arguments: %{"path" => "../etc/passwd"}})

      assert msg =~ "traversal"
    end

    test "returns diagnostic when line slice is out of range" do
      lines = "line1\nline2\n"
      content = Base.encode64(lines)

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib/foo.ex", _req ->
          json_resp(%{"content" => content, "encoding" => "base64", "type" => "file"})
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))

      assert {:ok, text} =
               handler.(%{
                 name: "get_file_contents",
                 arguments: %{"path" => "lib/foo.ex", "start_line" => 100, "end_line" => 200}
               })

      assert text =~ "no content in lines"
    end
  end

  # --- search_code dispatch ---

  describe "search_code" do
    test "returns formatted search results" do
      items = [
        %{"path" => "lib/foo.ex", "text_matches" => [%{"fragment" => "def bar do"}]}
      ]

      req =
        mock_req(fn :get, "/search/code", _req ->
          json_resp(%{"items" => items, "total_count" => 1})
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))
      assert {:ok, text} = handler.(%{name: "search_code", arguments: %{"query" => "def bar"}})
      assert is_binary(text)
      assert text =~ "lib/foo.ex"
    end

    test "handles text_matches with missing fragment keys" do
      items = [
        %{"path" => "lib/foo.ex", "text_matches" => [%{"object_type" => "FileContent"}]}
      ]

      req =
        mock_req(fn :get, "/search/code", _req ->
          json_resp(%{"items" => items, "total_count" => 1})
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))
      assert {:ok, text} = handler.(%{name: "search_code", arguments: %{"query" => "bar"}})
      assert text =~ "lib/foo.ex"
    end

    test "returns message when no results" do
      req =
        mock_req(fn :get, "/search/code", _req ->
          json_resp(%{"items" => [], "total_count" => 0})
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))
      assert {:ok, text} = handler.(%{name: "search_code", arguments: %{"query" => "zzz"}})
      assert text =~ "No results"
    end
  end

  # --- list_directory dispatch ---

  describe "list_directory" do
    test "returns formatted directory listing" do
      entries = [
        %{"name" => "foo.ex", "type" => "file", "path" => "lib/foo.ex"},
        %{"name" => "bar", "type" => "dir", "path" => "lib/bar"}
      ]

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib", _req ->
          json_resp(entries)
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))
      assert {:ok, text} = handler.(%{name: "list_directory", arguments: %{"path" => "lib"}})
      assert is_binary(text)
      assert text =~ "foo.ex"
      assert text =~ "bar"
    end

    test "returns error on 404" do
      req =
        mock_req(fn :get, "/repos/owner/repo/contents/nonexistent", _req ->
          json_resp(%{"message" => "Not Found"}, 404)
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))

      assert {:error, msg} =
               handler.(%{name: "list_directory", arguments: %{"path" => "nonexistent"}})

      assert is_binary(msg)
    end
  end

  # --- Unknown tool ---

  describe "unknown tool" do
    test "returns error for unrecognized tool name" do
      handler = GithubReadHandler.build(@repo, @ref, [])
      assert {:error, msg} = handler.(%{name: "unknown_tool", arguments: %{}})
      assert msg =~ "unknown_tool"
    end
  end

  # --- Error resilience ---

  describe "error handling" do
    test "rate limit returns readable error" do
      req =
        mock_req(fn :get, _path, _req ->
          json_resp(%{"message" => "rate limit exceeded"}, 429)
        end)

      handler = GithubReadHandler.build(@repo, @ref, gh_opts(req))
      assert {:error, msg} = handler.(%{name: "get_file_contents", arguments: %{"path" => "x"}})
      assert is_binary(msg)
    end
  end
end
