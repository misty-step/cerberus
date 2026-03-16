defmodule Cerberus.API do
  @moduledoc """
  HTTP API for dispatching review runs.

  Thin REST surface over `Cerberus.Pipeline`. Authenticated via Bearer token.
  Designed to be called by the thin GHA action (`api/action.yml`).

  ## Endpoints

      POST /api/reviews    — start a review run (202)
      GET  /api/reviews/:id — poll status/results (200 | 404)
      GET  /api/health      — liveness probe (200)
  """

  use Plug.Router

  plug :match
  plug Plug.Parsers, parsers: [:json], json_decoder: Jason
  plug :check_auth
  plug :dispatch

  @impl true
  def init(opts), do: opts

  @impl true
  def call(conn, opts) do
    conn
    |> put_private(:api_key, Keyword.get(opts, :api_key))
    |> put_private(:store, Keyword.get(opts, :store))
    |> put_private(:pipeline, Keyword.get(opts, :pipeline))
    |> super(opts)
  end

  # --- Auth ---

  # Health check must be unauthenticated for Fly/Sprite health probes.
  defp check_auth(%Plug.Conn{request_path: "/api/health"} = conn, _opts), do: conn

  defp check_auth(conn, _opts) do
    expected = conn.private[:api_key] || api_key_from_env()

    case {expected, get_req_header(conn, "authorization")} do
      {key, ["Bearer " <> token]} when is_binary(key) and key != "" and token == key ->
        conn

      _ ->
        conn
        |> put_resp_content_type("application/json")
        |> send_resp(401, Jason.encode!(%{error: "missing_or_invalid_auth"}))
        |> halt()
    end
  end

  defp api_key_from_env do
    case System.get_env("CERBERUS_API_KEY") do
      nil -> nil
      "" -> nil
      key -> key
    end
  end

  # --- Routes ---

  get "/api/health" do
    json(conn, 200, %{status: "ok"})
  end

  post "/api/reviews" do
    with {:ok, params} <- validate_review_params(conn.body_params) do
      store = conn.private[:store] || Cerberus.Store

      try do
        case Cerberus.Store.create_review_run(store, params) do
          review_id when is_integer(review_id) ->
            maybe_start_pipeline(conn.private[:pipeline], review_id, params)
            json(conn, 202, %{review_id: review_id, status: "queued"})

          {:error, reason} ->
            require Logger
            Logger.error("Store error creating review run: #{inspect(reason)}")
            json(conn, 500, %{error: "store_error"})
        end
      catch
        :exit, reason ->
          require Logger
          Logger.error("Store unavailable: #{inspect(reason)}")
          json(conn, 500, %{error: "store_unavailable"})
      end
    else
      {:error, reason} ->
        json(conn, 422, %{error: reason})
    end
  end

  get "/api/reviews/:id" do
    store = conn.private[:store] || Cerberus.Store

    try do
      review_id = String.to_integer(id)

      case Cerberus.Store.get_review_run(store, review_id) do
        {:ok, run} -> json(conn, 200, run)
        {:error, :not_found} -> json(conn, 404, %{error: "not_found"})
      end
    rescue
      ArgumentError -> json(conn, 404, %{error: "not_found"})
    end
  end

  match _ do
    json(conn, 404, %{error: "not_found"})
  end

  # --- Helpers ---

  defp json(conn, status, body) do
    conn
    |> put_resp_content_type("application/json")
    |> send_resp(status, Jason.encode!(body))
  end

  defp validate_review_params(params) do
    repo = params["repo"]
    pr_number = params["pr_number"]
    head_sha = params["head_sha"]

    cond do
      not is_binary(repo) or repo == "" ->
        {:error, "missing required field: repo"}

      not is_integer(pr_number) ->
        {:error, "missing or invalid field: pr_number (must be integer)"}

      not is_binary(head_sha) or head_sha == "" ->
        {:error, "missing required field: head_sha"}

      true ->
        {:ok, %{repo: repo, pr_number: pr_number, head_sha: head_sha,
                github_token: params["github_token"],
                model: params["model"]}}
    end
  end

  defp maybe_start_pipeline(nil, _id, _params), do: :ok
  defp maybe_start_pipeline(pipeline_fn, id, params), do: pipeline_fn.(id, params)
end
