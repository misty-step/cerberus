import Config

config :cerberus_elixir,
  repo_root:
    System.get_env("CERBERUS_REPO_ROOT") || Application.get_env(:cerberus_elixir, :repo_root),
  database_path:
    System.get_env("CERBERUS_DB_PATH") || Application.get_env(:cerberus_elixir, :database_path)
