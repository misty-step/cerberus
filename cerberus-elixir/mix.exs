defmodule Cerberus.MixProject do
  use Mix.Project

  def project do
    [
      app: :cerberus_elixir,
      version: "0.1.0",
      elixir: "~> 1.19",
      start_permanent: Mix.env() == :prod,
      deps: deps()
    ]
  end

  # Run "mix help compile.app" to learn about applications.
  def application do
    [
      extra_applications: [:logger],
      mod: {Cerberus.Application, []}
    ]
  end

  defp deps do
    [
      {:exqlite, "~> 0.34"},
      {:jason, "~> 1.4"},
      {:req, "~> 0.5"},
      {:req_llm, "~> 1.2"},
      {:yaml_elixir, "~> 2.12"}
    ]
  end
end
