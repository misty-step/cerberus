defmodule Cerberus.MixProject do
  use Mix.Project

  def project do
    [
      app: :cerberus_elixir,
      version: "0.1.0",
      elixir: "~> 1.19",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      escript: escript(),
      deps: deps()
    ]
  end

  # Run "mix help compile.app" to learn about applications.
  def application do
    [
      extra_applications: [:logger, :telemetry],
      mod: {Cerberus.Application, []}
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]

  defp escript do
    [
      app: nil,
      main_module: Cerberus.Command,
      name: "cerberus"
    ]
  end

  defp deps do
    [
      {:jason, "~> 1.4"},
      {:opentelemetry_api, "~> 1.5"},
      {:opentelemetry, "~> 1.7"},
      {:opentelemetry_exporter, "~> 1.10"},
      {:req, "~> 0.5"},
      {:req_llm, "~> 1.2"},
      {:yaml_elixir, "~> 2.12"}
    ]
  end
end
