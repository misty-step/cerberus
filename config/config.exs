import Config

config :cerberus_elixir,
  repo_root: Path.expand("..", __DIR__),
  prompt_glob: "pi/agents/*.md"

config :logger, :default_handler, config: [type: :standard_error]

if config_env() == :test do
  import_config "test.exs"
end
