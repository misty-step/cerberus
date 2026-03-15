defmodule Cerberus.Config do
  @moduledoc false

  @spec load(keyword()) :: {:ok, map()} | {:error, term()}
  def load(opts \\ []) do
    repo_root =
      opts
      |> Keyword.get(:repo_root, Cerberus.repo_root())
      |> normalize_repo_root()

    with {:ok, defaults} <- YamlElixir.read_from_file(Path.join(repo_root, "defaults/config.yml")),
         {:ok, prompts} <- load_prompts(repo_root) do
      {:ok, %{"defaults" => defaults, "prompts" => prompts}}
    end
  end

  defp normalize_repo_root(candidate_root) do
    defaults_path = Path.join(candidate_root, "defaults/config.yml")

    cond do
      File.exists?(defaults_path) ->
        candidate_root

      File.exists?(Path.join([candidate_root, "..", "defaults/config.yml"])) ->
        Path.expand("..", candidate_root)

      true ->
        candidate_root
    end
  end

  defp load_prompts(repo_root) do
    prompt_glob = Application.get_env(:cerberus_elixir, :prompt_glob, "pi/agents/*.md")

    prompts =
      repo_root
      |> Path.join(prompt_glob)
      |> Path.wildcard()
      |> Enum.sort()
      |> Enum.reduce_while({:ok, %{}}, fn path, {:ok, acc} ->
        case File.read(path) do
          {:ok, prompt} ->
            key = path |> Path.basename(".md")
            {:cont, {:ok, Map.put(acc, key, prompt)}}

          {:error, reason} ->
            {:halt, {:error, {:prompt_read_failed, path, reason}}}
        end
      end)

    case prompts do
      {:ok, map} when map_size(map) > 0 -> {:ok, map}
      {:ok, _empty} -> {:error, :no_prompts_found}
      error -> error
    end
  end
end
