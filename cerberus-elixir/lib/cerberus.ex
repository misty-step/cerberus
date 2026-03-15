defmodule Cerberus do
  @moduledoc """
  Shared path helpers for the Elixir Cerberus scaffold.
  """

  @spec repo_root() :: String.t()
  def repo_root do
    Application.fetch_env!(:cerberus_elixir, :repo_root)
  end

  @spec defaults_path() :: String.t()
  def defaults_path do
    Path.join(repo_root(), "defaults/config.yml")
  end

  @spec prompt_glob() :: String.t()
  def prompt_glob do
    Application.get_env(:cerberus_elixir, :prompt_glob, "pi/agents/*.md")
  end

  @spec prompts_path() :: String.t()
  def prompts_path do
    Path.join(repo_root(), prompt_glob())
  end

  @spec database_path() :: String.t()
  def database_path do
    Application.fetch_env!(:cerberus_elixir, :database_path)
  end
end
