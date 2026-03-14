import Config

config :cerberus_elixir,
  repo_root: Path.expand("../..", __DIR__),
  database_path: Path.expand("../tmp/cerberus.sqlite3", __DIR__),
  prompt_glob: ".opencode/agents/*.md"
