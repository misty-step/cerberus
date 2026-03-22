defmodule Cerberus.MixProject do
  use Mix.Project

  def project do
    [
      app: :cerberus_elixir,
      version: "0.1.0",
      elixir: "~> 1.19",
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      releases: releases()
    ]
  end

  # Run "mix help compile.app" to learn about applications.
  def application do
    [
      extra_applications: [:logger, :telemetry],
      mod: {Cerberus.Application, []}
    ]
  end

  defp deps do
    [
      {:bandit, "~> 1.6"},
      {:exqlite, "~> 0.34"},
      {:jason, "~> 1.4"},
      {:opentelemetry_api, "~> 1.5"},
      {:opentelemetry, "~> 1.7"},
      {:opentelemetry_exporter, "~> 1.10"},
      {:plug, "~> 1.16"},
      {:req, "~> 0.5"},
      {:req_llm, "~> 1.2"},
      {:yaml_elixir, "~> 2.12"}
    ]
  end

  defp releases do
    [
      cerberus: [
        applications: [cerberus_elixir: :permanent]
      ]
    ]
  end
end
