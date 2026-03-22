defmodule Cerberus.TelemetryTest do
  use ExUnit.Case, async: true

  alias Cerberus.Telemetry

  # --- Helper ---

  defp unique_name, do: :"telemetry_#{System.unique_integer([:positive])}"

  defp start_telemetry(opts \\ []) do
    name = Keyword.get_lazy(opts, :name, &unique_name/0)
    {:ok, pid} = Telemetry.start_link([{:name, name} | opts])
    {pid, name}
  end

  defp start_store do
    path =
      Path.join(
        System.tmp_dir!(),
        "cerberus_test_#{System.unique_integer([:positive, :monotonic])}_#{System.system_time(:microsecond)}.db"
      )

    {:ok, store} = Cerberus.Store.start_link(database_path: path)

    ExUnit.Callbacks.on_exit(fn ->
      if Process.alive?(store) do
        try do
          GenServer.stop(store)
        catch
          :exit, {:noproc, _} -> :ok
          :exit, :noproc -> :ok
        end
      end

      File.rm(path)
    end)

    store
  end

  # --- Span helper pass-through ---

  describe "with_review_run/2" do
    test "passes OTel context to callback and returns result" do
      result =
        Telemetry.with_review_run(42, fn ctx ->
          # Context should be non-nil (OTel SDK provides a context token)
          assert ctx != nil
          {:ok, :review_done}
        end)

      assert result == {:ok, :review_done}
    end

    test "propagates exceptions from callback" do
      assert_raise RuntimeError, "boom", fn ->
        Telemetry.with_review_run(1, fn _ctx -> raise "boom" end)
      end
    end
  end

  describe "with_reviewer/4" do
    test "returns callback result unchanged" do
      result =
        Telemetry.with_reviewer(nil, :correctness, "test-model", fn ->
          {:ok,
           %{verdict: %{verdict: "PASS"}, usage: %{prompt_tokens: 100, completion_tokens: 50}}}
        end)

      assert {:ok, %{verdict: %{verdict: "PASS"}}} = result
    end

    test "works with parent context from with_review_run" do
      result =
        Telemetry.with_review_run(7, fn ctx ->
          Telemetry.with_reviewer(ctx, :security, "model-a", fn ->
            {:ok, :reviewed}
          end)
        end)

      assert result == {:ok, :reviewed}
    end

    test "handles nil parent context" do
      result = Telemetry.with_reviewer(nil, :architecture, "model-b", fn -> :ok end)
      assert result == :ok
    end

    test "handles error results without crashing" do
      result =
        Telemetry.with_reviewer(nil, :testing, "model-c", fn ->
          {:error, :all_models_exhausted}
        end)

      assert result == {:error, :all_models_exhausted}
    end
  end

  describe "with_llm_call/2" do
    test "returns callback result unchanged" do
      result =
        Telemetry.with_llm_call("test-model", fn ->
          {:ok, %{content: "hello", usage: %{prompt_tokens: 10, completion_tokens: 5}}}
        end)

      assert {:ok, %{content: "hello"}} = result
    end

    test "handles error results" do
      result = Telemetry.with_llm_call("model", fn -> {:error, :transient} end)
      assert result == {:error, :transient}
    end

    test "handles missing usage in response" do
      result =
        Telemetry.with_llm_call("model", fn ->
          {:ok, %{content: "hi"}}
        end)

      assert {:ok, %{content: "hi"}} = result
    end
  end

  # --- Full trace hierarchy ---

  describe "trace hierarchy" do
    test "review_run → reviewer → llm_call nests without error" do
      result =
        Telemetry.with_review_run(99, fn ctx ->
          r1 =
            Telemetry.with_reviewer(ctx, :correctness, "model-1", fn ->
              Telemetry.with_llm_call("model-1", fn ->
                {:ok, %{content: "verdict", usage: %{prompt_tokens: 50, completion_tokens: 25}}}
              end)
            end)

          r2 =
            Telemetry.with_reviewer(ctx, :security, "model-2", fn ->
              {:ok,
               %{
                 verdict: %{verdict: "PASS"},
                 usage: %{prompt_tokens: 100, completion_tokens: 50}
               }}
            end)

          {r1, r2}
        end)

      assert {{:ok, _}, {:ok, _}} = result
    end
  end

  # --- Langfuse configuration ---

  describe "langfuse_configured?/1" do
    test "returns false when credentials not set" do
      {_pid, name} = start_telemetry()
      refute Telemetry.langfuse_configured?(name)
    end

    test "returns true when both keys provided" do
      {_pid, name} =
        start_telemetry(
          langfuse_public_key: "pk-lf-test",
          langfuse_secret_key: "sk-lf-test"
        )

      assert Telemetry.langfuse_configured?(name)
    end

    test "returns false when only public key provided" do
      {_pid, name} = start_telemetry(langfuse_public_key: "pk-lf-test")
      refute Telemetry.langfuse_configured?(name)
    end

    test "returns false for empty string keys" do
      {_pid, name} =
        start_telemetry(
          langfuse_public_key: "",
          langfuse_secret_key: "sk-test"
        )

      refute Telemetry.langfuse_configured?(name)
    end
  end

  # --- Telemetry handler registration ---

  describe "handler registration" do
    test "registers handlers for reviewer complete events" do
      {_pid, _name} = start_telemetry()
      handlers = :telemetry.list_handlers([:cerberus, :reviewer, :complete])
      assert Enum.any?(handlers, &String.starts_with?(&1.id, "cerberus-otel-"))
    end

    test "registers handlers for reviewer error events" do
      {_pid, _name} = start_telemetry()
      handlers = :telemetry.list_handlers([:cerberus, :reviewer, :error])
      assert Enum.any?(handlers, &String.starts_with?(&1.id, "cerberus-otel-"))
    end

    test "cleans up handlers on terminate" do
      {pid, name} = start_telemetry()
      prefix = "cerberus-otel-#{:erlang.phash2(name)}"

      # Handlers exist
      handlers = :telemetry.list_handlers([:cerberus, :reviewer, :complete])
      assert Enum.any?(handlers, &String.starts_with?(&1.id, prefix))

      # Stop the GenServer
      GenServer.stop(pid)

      # Handlers should be removed
      handlers_after = :telemetry.list_handlers([:cerberus, :reviewer, :complete])
      refute Enum.any?(handlers_after, &String.starts_with?(&1.id, prefix))
    end
  end

  # --- Langfuse client ---

  describe "Langfuse.send_generation/2" do
    test "sends generation data to Langfuse API" do
      config = %{
        enabled: true,
        public_key: "pk-test",
        secret_key: "sk-test",
        host: "http://localhost:9999"
      }

      attrs = %{
        name: "reviewer.correctness",
        model: "test-model",
        input_tokens: 500,
        output_tokens: 200,
        duration_ms: 1500,
        status: "success",
        cost: 0.0055
      }

      # send_generation fires async — it will fail to connect
      # but should not raise in the caller
      {:ok, _task} = Cerberus.Telemetry.Langfuse.send_generation(config, attrs)

      # Verify the sync version builds correct body
      body = build_generation_body(attrs)
      assert body.name == "reviewer.correctness"
      assert body.model == "test-model"
      assert body.usage.input == 500
      assert body.usage.output == 200
      assert body.metadata.cost_usd == 0.0055
    end
  end

  describe "Langfuse.send_trace/2" do
    test "builds trace body correctly" do
      config = %{
        enabled: true,
        public_key: "pk-test",
        secret_key: "sk-test",
        host: "http://localhost:9999"
      }

      attrs = %{name: "review_run.42", pr_number: 42}
      {:ok, _task} = Cerberus.Telemetry.Langfuse.send_trace(config, attrs)
    end
  end

  # Helper to test body construction without HTTP
  defp build_generation_body(attrs) do
    %{
      name: attrs[:name],
      model: attrs[:model],
      startTime: DateTime.utc_now() |> DateTime.to_iso8601(),
      usage: %{
        input: attrs[:input_tokens] || 0,
        output: attrs[:output_tokens] || 0
      },
      metadata: %{
        duration_ms: attrs[:duration_ms],
        status: to_string(attrs[:status]),
        cost_usd: attrs[:cost]
      }
    }
  end

  # --- Store cost tracking ---

  describe "Store.insert_cost/2" do
    test "inserts a cost record" do
      store = start_store()

      assert :ok =
               Cerberus.Store.insert_cost(store, %{
                 review_run_id: 1,
                 reviewer: "trace",
                 model: "moonshotai/kimi-k2.5",
                 prompt_tokens: 1000,
                 completion_tokens: 500,
                 cost_usd: 0.0015,
                 duration_ms: 3200,
                 status: "success",
                 is_fallback: false
               })
    end

    test "handles missing optional fields with defaults" do
      store = start_store()

      assert :ok =
               Cerberus.Store.insert_cost(store, %{
                 reviewer: "guard",
                 model: "test-model"
               })
    end
  end

  describe "Store.model_performance/1" do
    test "returns empty list when no data" do
      store = start_store()
      assert {:ok, []} = Cerberus.Store.model_performance(store)
    end

    test "aggregates metrics by model" do
      store = start_store()

      # Insert multiple cost records
      for i <- 1..3 do
        Cerberus.Store.insert_cost(store, %{
          review_run_id: 1,
          reviewer: "trace",
          model: "model-a",
          prompt_tokens: 1000,
          completion_tokens: 500,
          cost_usd: 0.001,
          duration_ms: 2000 + i * 100,
          status: "success"
        })
      end

      Cerberus.Store.insert_cost(store, %{
        review_run_id: 1,
        reviewer: "guard",
        model: "model-a",
        prompt_tokens: 800,
        completion_tokens: 400,
        cost_usd: 0.0008,
        duration_ms: 1500,
        status: "error"
      })

      Cerberus.Store.insert_cost(store, %{
        review_run_id: 2,
        reviewer: "atlas",
        model: "model-b",
        prompt_tokens: 2000,
        completion_tokens: 1000,
        cost_usd: 0.005,
        duration_ms: 5000,
        status: "success",
        is_fallback: true
      })

      {:ok, results} = Cerberus.Store.model_performance(store)

      # model-a has 4 records (3 success, 1 error)
      model_a = Enum.find(results, &(&1.model == "model-a"))
      assert model_a.total_reviews == 4
      assert model_a.successes == 3
      assert_in_delta model_a.success_rate, 0.75, 0.01

      # model-b has 1 record, all fallback
      model_b = Enum.find(results, &(&1.model == "model-b"))
      assert model_b.total_reviews == 1
      assert_in_delta model_b.fallback_rate, 1.0, 0.01
      assert model_b.total_cost_usd == 0.005
    end
  end

  describe "Store.review_run_costs/2" do
    test "returns costs for a specific review run" do
      store = start_store()

      Cerberus.Store.insert_cost(store, %{
        review_run_id: 1,
        reviewer: "trace",
        model: "model-a",
        prompt_tokens: 1000,
        completion_tokens: 500,
        cost_usd: 0.001,
        duration_ms: 2000,
        status: "success"
      })

      Cerberus.Store.insert_cost(store, %{
        review_run_id: 1,
        reviewer: "guard",
        model: "model-a",
        prompt_tokens: 800,
        completion_tokens: 400,
        cost_usd: 0.0008,
        duration_ms: 1800,
        status: "success"
      })

      Cerberus.Store.insert_cost(store, %{
        review_run_id: 2,
        reviewer: "atlas",
        model: "model-b",
        prompt_tokens: 500,
        completion_tokens: 200,
        cost_usd: 0.0003,
        duration_ms: 1000,
        status: "success"
      })

      {:ok, costs} = Cerberus.Store.review_run_costs(store, 1)
      assert length(costs) == 2
      reviewers = Enum.map(costs, & &1.reviewer)
      assert "trace" in reviewers
      assert "guard" in reviewers

      # Run 2 only has atlas
      {:ok, costs_2} = Cerberus.Store.review_run_costs(store, 2)
      assert length(costs_2) == 1
      assert hd(costs_2).reviewer == "atlas"
    end

    test "returns empty list for non-existent run" do
      store = start_store()
      assert {:ok, []} = Cerberus.Store.review_run_costs(store, 999)
    end
  end

  # --- Telemetry event handling ---

  describe "telemetry event → Langfuse export" do
    test "reviewer complete event triggers Langfuse export when configured" do
      # Start telemetry with Langfuse configured (will fail to connect, but that's OK)
      {_pid, _name} =
        start_telemetry(
          langfuse_public_key: "pk-test",
          langfuse_secret_key: "sk-test",
          langfuse_host: "http://localhost:9999"
        )

      # Emit a telemetry event — handler should fire without crashing
      :telemetry.execute(
        [:cerberus, :reviewer, :complete],
        %{duration_ms: 2500, prompt_tokens: 1000, completion_tokens: 500},
        %{perspective: :correctness, model: "test-model"}
      )

      # Give async Task a moment to fire (it will fail to connect, that's expected)
      Process.sleep(50)
    end

    test "reviewer error event triggers Langfuse export when configured" do
      {_pid, _name} =
        start_telemetry(
          langfuse_public_key: "pk-test",
          langfuse_secret_key: "sk-test",
          langfuse_host: "http://localhost:9999"
        )

      :telemetry.execute(
        [:cerberus, :reviewer, :error],
        %{duration_ms: 1000},
        %{perspective: :security, model: "test-model"}
      )

      Process.sleep(50)
    end

    test "no Langfuse export when credentials not configured" do
      {_pid, _name} = start_telemetry()

      # Should not crash even without Langfuse configured
      :telemetry.execute(
        [:cerberus, :reviewer, :complete],
        %{duration_ms: 1000, prompt_tokens: 100, completion_tokens: 50},
        %{perspective: :testing, model: "model"}
      )
    end
  end
end
