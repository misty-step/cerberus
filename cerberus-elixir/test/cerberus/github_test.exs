defmodule Cerberus.GitHubTest do
  use ExUnit.Case, async: true

  alias Cerberus.GitHub

  @repo "owner/repo"
  @pr 42

  # --- Test helpers ---

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

  defp test_opts(req), do: [req: req, max_retries: 3, retry_delay: fn _ -> :ok end]

  # --- fetch_pr_context ---

  describe "fetch_pr_context/3" do
    test "returns structured PR metadata on success" do
      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42", _req ->
          json_resp(%{
            "title" => "Add feature",
            "user" => %{"login" => "alice"},
            "head" => %{"ref" => "feat/x", "sha" => "abc123"},
            "base" => %{"ref" => "main"},
            "body" => "Description"
          })
        end)

      assert {:ok, ctx} = GitHub.fetch_pr_context(@repo, @pr, test_opts(req))
      assert ctx.title == "Add feature"
      assert ctx.author == "alice"
      assert ctx.head_ref == "feat/x"
      assert ctx.base_ref == "main"
      assert ctx.head_sha == "abc123"
      assert ctx.body == "Description"
    end

    test "returns auth error on 401" do
      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42", _req ->
          json_resp(%{"message" => "Bad credentials"}, 401)
        end)

      assert {:error, {:auth, _}} = GitHub.fetch_pr_context(@repo, @pr, test_opts(req))
    end

    test "returns permissions error on 403" do
      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42", _req ->
          json_resp(%{"message" => "Forbidden"}, 403)
        end)

      assert {:error, {:permissions, _}} = GitHub.fetch_pr_context(@repo, @pr, test_opts(req))
    end
  end

  # --- fetch_pr_diff ---

  describe "fetch_pr_diff/3" do
    test "returns raw diff string" do
      diff = "diff --git a/file.ex b/file.ex\n+new line"

      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42", _req ->
          json_resp(diff)
        end)

      assert {:ok, ^diff} = GitHub.fetch_pr_diff(@repo, @pr, test_opts(req))
    end
  end

  # --- fetch_comments + find_comment_by_marker ---

  describe "fetch_comments/3" do
    test "returns list of comments" do
      comments = [
        %{"id" => 1, "body" => "lgtm", "user" => %{"login" => "bob"}},
        %{"id" => 2, "body" => "nit", "user" => %{"login" => "carol"}}
      ]

      req =
        mock_req(fn :get, "/repos/owner/repo/issues/42/comments", _req ->
          json_resp(comments)
        end)

      assert {:ok, ^comments} = GitHub.fetch_comments(@repo, @pr, test_opts(req))
    end

    test "paginates across multiple pages" do
      page1 = Enum.map(1..100, &%{"id" => &1, "body" => "c#{&1}"})
      page2 = [%{"id" => 101, "body" => "last"}]

      req =
        mock_req(fn :get, "/repos/owner/repo/issues/42/comments", request ->
          page = extract_page(request.url.query)

          case page do
            "1" -> json_resp(page1)
            "2" -> json_resp(page2)
          end
        end)

      assert {:ok, all} = GitHub.fetch_comments(@repo, @pr, test_opts(req))
      assert length(all) == 101
    end
  end

  describe "find_comment_by_marker/2" do
    test "returns comment ID when marker found" do
      comments = [
        %{"id" => 10, "body" => "<!-- cerberus:trace -->\nReview"},
        %{"id" => 20, "body" => "lgtm"}
      ]

      assert GitHub.find_comment_by_marker(comments, "<!-- cerberus:trace -->") == 10
    end

    test "returns nil when marker not found" do
      comments = [%{"id" => 1, "body" => "no marker here"}]
      assert GitHub.find_comment_by_marker(comments, "<!-- cerberus:trace -->") == nil
    end
  end

  # --- upsert_comment ---

  describe "upsert_comment/5" do
    test "creates comment when marker not found" do
      marker = "<!-- cerberus:trace -->"
      body = "#{marker}\nReview content"

      req =
        mock_req(fn
          :get, "/repos/owner/repo/issues/42/comments", _req ->
            json_resp([%{"id" => 1, "body" => "unrelated"}])

          :post, "/repos/owner/repo/issues/42/comments", _req ->
            json_resp(%{"id" => 99, "body" => body}, 201)
        end)

      assert {:ok, %{body: %{"id" => 99}}} =
               GitHub.upsert_comment(@repo, @pr, marker, body, test_opts(req))
    end

    test "updates comment when marker found" do
      marker = "<!-- cerberus:trace -->"
      body = "#{marker}\nUpdated review"

      req =
        mock_req(fn
          :get, "/repos/owner/repo/issues/42/comments", _req ->
            json_resp([%{"id" => 55, "body" => "<!-- cerberus:trace -->\nOld review"}])

          :patch, "/repos/owner/repo/issues/comments/55", _req ->
            json_resp(%{"id" => 55, "body" => body})
        end)

      assert {:ok, %{body: %{"id" => 55}}} =
               GitHub.upsert_comment(@repo, @pr, marker, body, test_opts(req))
    end
  end

  # --- PR reviews with inline comments ---

  describe "create_pr_review/6" do
    test "posts review with inline comments" do
      comments = [
        %{path: "lib/foo.ex", position: 5, body: "Bug here"},
        %{path: "lib/bar.ex", position: 10, body: "Security issue"}
      ]

      req =
        mock_req(fn :post, "/repos/owner/repo/pulls/42/reviews", _req ->
          json_resp(%{"id" => 777})
        end)

      assert {:ok, %{body: %{"id" => 777}}} =
               GitHub.create_pr_review(@repo, @pr, "abc123", "Summary", comments, test_opts(req))
    end

    test "caps inline comments at 30" do
      comments = Enum.map(1..50, &%{path: "f#{&1}.ex", position: &1, body: "Issue #{&1}"})

      req =
        mock_req(fn :post, "/repos/owner/repo/pulls/42/reviews", request ->
          {:ok, payload} = Jason.decode(request.body)
          assert length(payload["comments"]) == 30
          json_resp(%{"id" => 1})
        end)

      assert {:ok, _} =
               GitHub.create_pr_review(@repo, @pr, "abc123", "Body", comments, test_opts(req))
    end
  end

  describe "list_pr_reviews/3" do
    test "returns list of reviews" do
      reviews = [
        %{"id" => 1, "state" => "COMMENTED", "body" => "lgtm", "user" => %{"login" => "alice"}},
        %{"id" => 2, "state" => "APPROVED", "body" => "", "user" => %{"login" => "bob"}}
      ]

      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42/reviews", _req ->
          json_resp(reviews)
        end)

      assert {:ok, ^reviews} = GitHub.list_pr_reviews(@repo, @pr, test_opts(req))
    end
  end

  describe "list_pr_files/3" do
    test "returns changed files with patches" do
      files = [
        %{"filename" => "lib/foo.ex", "patch" => "@@ -1 +1,2 @@\n+added"},
        %{"filename" => "lib/bar.ex", "patch" => "@@ -1 +1 @@\n context"}
      ]

      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42/files", _req ->
          json_resp(files)
        end)

      assert {:ok, ^files} = GitHub.list_pr_files(@repo, @pr, test_opts(req))
    end
  end

  # --- Check runs ---

  describe "create_check_run/4" do
    test "creates check run in queued state" do
      req =
        mock_req(fn :post, "/repos/owner/repo/check-runs", _req ->
          json_resp(%{"id" => 500, "status" => "queued"}, 201)
        end)

      assert {:ok, %{body: %{"id" => 500}}} =
               GitHub.create_check_run(@repo, "abc123", "cerberus", test_opts(req))
    end
  end

  describe "update_check_run/4" do
    test "updates check run with conclusion" do
      attrs = %{status: "completed", conclusion: "success"}

      req =
        mock_req(fn :patch, "/repos/owner/repo/check-runs/500", _req ->
          json_resp(%{"id" => 500, "status" => "completed", "conclusion" => "success"})
        end)

      assert {:ok, %{body: %{"conclusion" => "success"}}} =
               GitHub.update_check_run(@repo, 500, attrs, test_opts(req))
    end
  end

  # --- Override comments ---

  describe "fetch_override_comments/3" do
    test "parses override comments with SHA and actor" do
      comments = [
        %{
          "id" => 1,
          "body" => "/cerberus override sha=abc1234 reason: hotfix",
          "user" => %{"login" => "alice"}
        },
        %{"id" => 2, "body" => "lgtm", "user" => %{"login" => "bob"}},
        %{"id" => 3, "body" => "/cerberus override sha=def5678", "user" => %{"login" => "carol"}}
      ]

      req =
        mock_req(fn :get, "/repos/owner/repo/issues/42/comments", _req ->
          json_resp(comments)
        end)

      assert {:ok, overrides} = GitHub.fetch_override_comments(@repo, @pr, test_opts(req))
      assert length(overrides) == 2
      assert hd(overrides).sha == "abc1234"
      assert hd(overrides).actor == "alice"
      assert List.last(overrides).sha == "def5678"
    end

    test "returns empty list when no overrides" do
      req =
        mock_req(fn :get, "/repos/owner/repo/issues/42/comments", _req ->
          json_resp([%{"id" => 1, "body" => "lgtm", "user" => %{"login" => "bob"}}])
        end)

      assert {:ok, []} = GitHub.fetch_override_comments(@repo, @pr, test_opts(req))
    end
  end

  # --- Retry with exponential backoff ---

  describe "transient error retry" do
    test "retries on 502 then succeeds" do
      {:ok, counter} = Agent.start_link(fn -> 0 end)

      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42", _req ->
          attempt = Agent.get_and_update(counter, fn n -> {n, n + 1} end)

          if attempt < 2 do
            json_resp(%{"message" => "Bad Gateway"}, 502)
          else
            json_resp(%{
              "title" => "OK",
              "user" => %{"login" => "a"},
              "head" => %{"ref" => "b", "sha" => "c"},
              "base" => %{"ref" => "d"},
              "body" => "e"
            })
          end
        end)

      assert {:ok, ctx} = GitHub.fetch_pr_context(@repo, @pr, test_opts(req))
      assert ctx.title == "OK"
      assert Agent.get(counter, & &1) == 3
    end

    test "returns transient error after max retries exhausted" do
      req =
        mock_req(fn :get, "/repos/owner/repo/pulls/42", _req ->
          json_resp(%{"message" => "Bad Gateway"}, 502)
        end)

      assert {:error, {:transient, _}} = GitHub.fetch_pr_context(@repo, @pr, test_opts(req))
    end
  end

  # --- Diff position mapping ---

  describe "build_position_map/1" do
    test "maps new-file line numbers to diff positions" do
      patch = """
      @@ -1,3 +1,4 @@
       line1
      +added
       line2
       line3\
      """

      map = GitHub.build_position_map(patch)
      # @@ header is position 1
      # " line1" is position 2 → new line 1
      # "+added" is position 3 → new line 2
      # " line2" is position 4 → new line 3
      # " line3" is position 5 → new line 4
      assert map[1] == 2
      assert map[2] == 3
      assert map[3] == 4
      assert map[4] == 5
    end

    test "handles multiple hunks" do
      patch = """
      @@ -1,2 +1,2 @@
       ctx
      +new1
      @@ -10,2 +10,2 @@
       ctx2
      +new2\
      """

      map = GitHub.build_position_map(patch)
      assert map[1] == 2
      assert map[2] == 3
      assert map[10] == 5
      assert map[11] == 6
    end

    test "returns empty map for nil" do
      assert GitHub.build_position_map(nil) == %{}
    end
  end

  # --- get_file_contents ---

  describe "get_file_contents/4" do
    test "returns decoded base64 file content" do
      content = Base.encode64("defmodule Foo do\n  def bar, do: :ok\nend\n")

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib/foo.ex", _req ->
          json_resp(%{"content" => content, "encoding" => "base64", "type" => "file"})
        end)

      assert {:ok, text} = GitHub.get_file_contents(@repo, "lib/foo.ex", "abc123", test_opts(req))
      assert text =~ "defmodule Foo"
    end

    test "passes ref as query param" do
      test_pid = self()

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib/foo.ex", request ->
          send(test_pid, {:query, request.url.query})
          content = Base.encode64("content")
          json_resp(%{"content" => content, "encoding" => "base64", "type" => "file"})
        end)

      {:ok, _} = GitHub.get_file_contents(@repo, "lib/foo.ex", "deadbeef", test_opts(req))
      assert_receive {:query, query}
      assert query =~ "ref=deadbeef"
    end

    test "returns http_error on 404" do
      req =
        mock_req(fn :get, "/repos/owner/repo/contents/nonexistent.ex", _req ->
          json_resp(%{"message" => "Not Found"}, 404)
        end)

      assert {:error, {:http_error, 404, _}} =
               GitHub.get_file_contents(@repo, "nonexistent.ex", "abc123", test_opts(req))
    end

    test "returns error when path is a directory" do
      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib", _req ->
          json_resp([%{"name" => "foo.ex", "type" => "file"}])
        end)

      assert {:error, {:not_a_file, "lib"}} =
               GitHub.get_file_contents(@repo, "lib", "abc123", test_opts(req))
    end

    test "rejects paths with traversal sequences" do
      assert {:error, {:invalid_path, "../etc/passwd"}} =
               GitHub.get_file_contents(@repo, "../etc/passwd", "abc123", [])
    end

    test "rejects URL-encoded path traversal" do
      assert {:error, {:invalid_path, "%2e%2e/etc/passwd"}} =
               GitHub.get_file_contents(@repo, "%2e%2e/etc/passwd", "abc123", [])
    end

    test "rejects absolute paths" do
      assert {:error, {:invalid_path, "/etc/passwd"}} =
               GitHub.get_file_contents(@repo, "/etc/passwd", "abc123", [])
    end

    test "returns file_too_large when content is null" do
      req =
        mock_req(fn :get, "/repos/owner/repo/contents/big.bin", _req ->
          json_resp(%{"type" => "file", "size" => 150_000_000, "content" => nil, "encoding" => "none"})
        end)

      assert {:error, {:file_too_large, "big.bin", 150_000_000}} =
               GitHub.get_file_contents(@repo, "big.bin", "abc123", test_opts(req))
    end
  end

  # --- search_code ---

  describe "search_code/4" do
    test "returns search results" do
      items = [
        %{"name" => "foo.ex", "path" => "lib/foo.ex",
          "text_matches" => [%{"fragment" => "def bar"}]}
      ]

      req =
        mock_req(fn :get, "/search/code", _req ->
          json_resp(%{"items" => items, "total_count" => 1})
        end)

      assert {:ok, ^items} = GitHub.search_code(@repo, "def bar", test_opts(req))
    end

    test "builds query with repo scope" do
      test_pid = self()

      req =
        mock_req(fn :get, "/search/code", request ->
          send(test_pid, {:query, request.url.query})
          json_resp(%{"items" => [], "total_count" => 0})
        end)

      {:ok, _} = GitHub.search_code(@repo, "pattern", test_opts(req))
      assert_receive {:query, query}
      params = URI.decode_query(query)
      assert params["q"] =~ "pattern"
      assert params["q"] =~ "repo:owner/repo"
    end

    test "includes path filter when provided" do
      test_pid = self()

      req =
        mock_req(fn :get, "/search/code", request ->
          send(test_pid, {:query, request.url.query})
          json_resp(%{"items" => [], "total_count" => 0})
        end)

      {:ok, _} = GitHub.search_code(@repo, "pattern", test_opts(req) ++ [path_filter: "lib/**"])
      assert_receive {:query, query}
      params = URI.decode_query(query)
      assert params["q"] =~ "path:lib/**"
    end

    test "returns empty list when no matches" do
      req =
        mock_req(fn :get, "/search/code", _req ->
          json_resp(%{"items" => [], "total_count" => 0})
        end)

      assert {:ok, []} = GitHub.search_code(@repo, "nonexistent_xyz", test_opts(req))
    end

    test "strips scope qualifiers from path_filter" do
      test_pid = self()

      req =
        mock_req(fn :get, "/search/code", request ->
          send(test_pid, {:query, request.url.query})
          json_resp(%{"items" => [], "total_count" => 0})
        end)

      {:ok, _} = GitHub.search_code(@repo, "pattern", test_opts(req) ++ [path_filter: "lib repo:evil/repo"])
      assert_receive {:query, query}
      params = URI.decode_query(query)
      refute params["q"] =~ "repo:evil"
    end

    test "strips injected repo: qualifiers from query" do
      test_pid = self()

      req =
        mock_req(fn :get, "/search/code", request ->
          send(test_pid, {:query, request.url.query})
          json_resp(%{"items" => [], "total_count" => 0})
        end)

      {:ok, _} = GitHub.search_code(@repo, "foo repo:evil/repo bar", test_opts(req))
      assert_receive {:query, query}
      params = URI.decode_query(query)
      refute params["q"] =~ "repo:evil"
      assert params["q"] =~ "repo:owner/repo"
    end
  end

  # --- list_directory ---

  describe "list_directory/4" do
    test "returns directory entries" do
      entries = [
        %{"name" => "foo.ex", "type" => "file", "path" => "lib/foo.ex"},
        %{"name" => "bar", "type" => "dir", "path" => "lib/bar"}
      ]

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib", _req ->
          json_resp(entries)
        end)

      assert {:ok, ^entries} = GitHub.list_directory(@repo, "lib", "abc123", test_opts(req))
    end

    test "returns error when path is a file" do
      req =
        mock_req(fn :get, "/repos/owner/repo/contents/lib/foo.ex", _req ->
          json_resp(%{"name" => "foo.ex", "type" => "file", "content" => "x"})
        end)

      assert {:error, {:not_a_directory, "lib/foo.ex"}} =
               GitHub.list_directory(@repo, "lib/foo.ex", "abc123", test_opts(req))
    end

    test "passes ref as query param" do
      test_pid = self()

      req =
        mock_req(fn :get, "/repos/owner/repo/contents/src", request ->
          send(test_pid, {:query, request.url.query})
          json_resp([%{"name" => "main.rs", "type" => "file"}])
        end)

      {:ok, _} = GitHub.list_directory(@repo, "src", "deadbeef", test_opts(req))
      assert_receive {:query, query}
      assert query =~ "ref=deadbeef"
    end
  end

  # --- Helpers ---

  defp extract_page(nil), do: "1"

  defp extract_page(query) do
    query
    |> URI.decode_query()
    |> Map.get("page", "1")
  end
end
