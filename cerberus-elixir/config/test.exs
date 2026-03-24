import Config

config :opentelemetry,
  traces_exporter: :none,
  processors: [
    otel_simple_processor: %{
      exporter: :none
    }
  ]

config :cerberus_elixir,
  api_port: 0,
  cli_overrides: [
    routing_result: %{
      panel: ["correctness"],
      reserves: [],
      model_tier: :flash,
      size_bucket: :small,
      routing_used: false
    },
    call_llm: &Cerberus.CLITestSupport.call_llm/1
  ]
