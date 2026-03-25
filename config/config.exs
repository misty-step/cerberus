import Config

config :cerberus_elixir,
  repo_root: Path.expand("..", __DIR__),
  prompt_glob: "pi/agents/*.md"

if config_env() == :test do
  import_config "test.exs"
end
