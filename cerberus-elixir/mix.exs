defmodule Cerberus.MixProject do
  use Mix.Project

  def project do
    [
      app: :cerberus_elixir,
      version: "0.1.0",
      elixir: "~> 1.19",
      start_permanent: Mix.env() == :prod,
      releases: releases(),
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

  defp releases do
    [
      cerberus: [
        include_executables_for: [:unix],
        applications: [runtime_tools: :permanent, cerberus_elixir: :permanent],
        steps: [:assemble, &copy_runtime_assets/1]
      ]
    ]
  end

  # Bundle the repo-owned reviewer assets into the assembled release so
  # container and tarball deployments do not depend on a source checkout.
  defp copy_runtime_assets(%Mix.Release{} = release) do
    repo_root = Path.expand("..", __DIR__)
    runtime_root = Path.join(release.path, "repo")

    for relative_path <- ["defaults", "pi/agents", "templates"] do
      source = Path.join(repo_root, relative_path)
      target = Path.join(runtime_root, relative_path)

      File.rm_rf!(target)
      File.mkdir_p!(Path.dirname(target))
      File.cp_r!(source, target)
    end

    release
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
end
