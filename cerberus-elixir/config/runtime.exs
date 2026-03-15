import Config

# --- Port ---
if port = System.get_env("PORT") do
  config :cerberus_elixir, api_port: String.to_integer(port)
end

# --- Repo root ---
if repo_root = System.get_env("CERBERUS_REPO_ROOT") do
  config :cerberus_elixir, repo_root: repo_root
end

# --- Database ---
if db_path = System.get_env("CERBERUS_DB_PATH") do
  config :cerberus_elixir, database_path: db_path
end

# --- Langfuse ---
config :cerberus_elixir,
  langfuse_public_key: System.get_env("LANGFUSE_PUBLIC_KEY"),
  langfuse_secret_key: System.get_env("LANGFUSE_SECRET_KEY"),
  langfuse_host: System.get_env("LANGFUSE_HOST") || "https://cloud.langfuse.com"

# --- Prod validations ---
if config_env() == :prod do
  unless System.get_env("CERBERUS_API_KEY") do
    IO.warn("CERBERUS_API_KEY not set — API auth will reject all requests")
  end

  unless System.get_env("CERBERUS_OPENROUTER_API_KEY") || System.get_env("OPENROUTER_API_KEY") do
    IO.warn("No OpenRouter API key set — LLM calls will fail")
  end

  config :logger, level: :info
end
