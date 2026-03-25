import Config

# --- Repo root ---
if repo_root = System.get_env("CERBERUS_REPO_ROOT") do
  config :cerberus_elixir, repo_root: repo_root
end

# --- Langfuse ---
config :cerberus_elixir,
  langfuse_public_key: System.get_env("LANGFUSE_PUBLIC_KEY"),
  langfuse_secret_key: System.get_env("LANGFUSE_SECRET_KEY"),
  langfuse_host: System.get_env("LANGFUSE_HOST") || "https://cloud.langfuse.com"

# --- Prod validations ---
if config_env() == :prod do
  unless System.get_env("CERBERUS_OPENROUTER_API_KEY") || System.get_env("OPENROUTER_API_KEY") do
    IO.warn("No OpenRouter API key set — CLI review calls will fail")
  end

  config :logger, level: :info
end
