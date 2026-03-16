defmodule Cerberus.APITest do
  use ExUnit.Case, async: true
  import Plug.Test
  import Plug.Conn

  alias Cerberus.API

  @api_key "test-cerberus-api-key"

  setup do
    db_path = Path.join(System.tmp_dir!(), "cerberus_api_test_#{System.unique_integer([:positive])}.db")
    {:ok, store} = Cerberus.Store.start_link(database_path: db_path)
    on_exit(fn -> File.rm(db_path) end)
    %{store: store}
  end

  defp call(conn, store) do
    API.call(conn, API.init(api_key: @api_key, store: store))
  end

  defp json_post(path, body, store) do
    conn(:post, path, Jason.encode!(body))
    |> put_req_header("content-type", "application/json")
    |> put_req_header("authorization", "Bearer #{@api_key}")
    |> call(store)
  end

  defp authed_get(path, store) do
    conn(:get, path)
    |> put_req_header("authorization", "Bearer #{@api_key}")
    |> call(store)
  end

  # --- Authentication ---

  describe "authentication" do
    test "rejects unauthenticated non-health requests", %{store: store} do
      conn = conn(:get, "/api/reviews/1") |> call(store)
      assert conn.status == 401
      body = Jason.decode!(conn.resp_body)
      assert body["error"] == "missing_or_invalid_auth"
    end

    test "rejects requests with wrong token", %{store: store} do
      conn =
        conn(:get, "/api/reviews/1")
        |> put_req_header("authorization", "Bearer wrong-key")
        |> call(store)

      assert conn.status == 401
    end

    test "accepts valid bearer token", %{store: store} do
      conn = authed_get("/api/health", store)
      assert conn.status == 200
    end

    test "health check bypasses auth", %{store: store} do
      conn = conn(:get, "/api/health") |> call(store)
      assert conn.status == 200
      body = Jason.decode!(conn.resp_body)
      assert body["status"] == "ok"
    end
  end

  # --- Health ---

  describe "GET /api/health" do
    test "returns ok with status", %{store: store} do
      conn = authed_get("/api/health", store)
      assert conn.status == 200
      body = Jason.decode!(conn.resp_body)
      assert body["status"] == "ok"
    end
  end

  # --- POST /api/reviews ---

  describe "POST /api/reviews" do
    test "rejects missing required fields", %{store: store} do
      conn = json_post("/api/reviews", %{}, store)
      assert conn.status == 422
      body = Jason.decode!(conn.resp_body)
      assert body["error"] =~ "missing"
    end

    test "rejects missing repo", %{store: store} do
      conn = json_post("/api/reviews", %{pr_number: 1, head_sha: "abc123"}, store)
      assert conn.status == 422
    end

    test "rejects empty string repo", %{store: store} do
      conn = json_post("/api/reviews", %{repo: "", pr_number: 1, head_sha: "abc123"}, store)
      assert conn.status == 422
    end

    test "rejects empty string head_sha", %{store: store} do
      conn = json_post("/api/reviews", %{repo: "org/repo", pr_number: 1, head_sha: ""}, store)
      assert conn.status == 422
    end

    test "rejects non-integer pr_number", %{store: store} do
      conn = json_post("/api/reviews", %{repo: "org/repo", pr_number: "abc", head_sha: "abc123"}, store)
      assert conn.status == 422
    end

    test "accepts valid review request and returns 202", %{store: store} do
      conn =
        json_post("/api/reviews", %{
          repo: "org/repo",
          pr_number: 42,
          head_sha: "abc123def456"
        }, store)

      assert conn.status == 202
      body = Jason.decode!(conn.resp_body)
      assert is_integer(body["review_id"])
      assert body["status"] == "queued"
    end
  end

  # --- GET /api/reviews/:id ---

  describe "GET /api/reviews/:id" do
    test "returns 404 for non-existent review", %{store: store} do
      conn = authed_get("/api/reviews/99999", store)
      assert conn.status == 404
      body = Jason.decode!(conn.resp_body)
      assert body["error"] == "not_found"
    end

    test "returns 404 for non-integer id", %{store: store} do
      conn = authed_get("/api/reviews/abc", store)
      assert conn.status == 404
    end

    test "returns queued review status after creation", %{store: store} do
      post_conn =
        json_post("/api/reviews", %{
          repo: "org/repo",
          pr_number: 42,
          head_sha: "abc123def456"
        }, store)

      assert post_conn.status == 202
      %{"review_id" => id} = Jason.decode!(post_conn.resp_body)

      conn = authed_get("/api/reviews/#{id}", store)
      assert conn.status == 200
      body = Jason.decode!(conn.resp_body)
      assert body["review_id"] == id
      assert body["status"] == "queued"
      assert body["repo"] == "org/repo"
      assert body["pr_number"] == 42
    end

    test "ignores unrecognized fields in request", %{store: store} do
      post_conn =
        json_post("/api/reviews", %{
          repo: "org/repo",
          pr_number: 42,
          head_sha: "abc123",
          extra_field: "should-be-ignored"
        }, store)

      %{"review_id" => id} = Jason.decode!(post_conn.resp_body)

      conn = authed_get("/api/reviews/#{id}", store)
      body = Jason.decode!(conn.resp_body)
      refute Map.has_key?(body, "extra_field")
    end
  end

  # --- Error handling ---

  describe "POST /api/reviews error handling" do
    test "returns 500 when store fails", %{store: _store} do
      # Use a fake store pid that will crash
      {:ok, dead_store} = Agent.start_link(fn -> nil end)
      Agent.stop(dead_store)

      conn =
        conn(:post, "/api/reviews", Jason.encode!(%{repo: "org/repo", pr_number: 42, head_sha: "abc"}))
        |> put_req_header("content-type", "application/json")
        |> put_req_header("authorization", "Bearer #{@api_key}")
        |> API.call(API.init(api_key: @api_key, store: dead_store))

      # GenServer call to dead process will raise
      assert conn.status == 500
    end
  end

  # --- 404 ---

  describe "unknown routes" do
    test "returns 404", %{store: store} do
      conn = authed_get("/api/nonexistent", store)
      assert conn.status == 404
    end
  end
end
