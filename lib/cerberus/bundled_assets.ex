defmodule Cerberus.BundledAssets do
  @moduledoc false

  @project_root Path.expand("../..", __DIR__)
  @defaults_path Path.join(@project_root, "defaults/config.yml")
  @prompt_paths Path.wildcard(Path.join(@project_root, "pi/agents/*.md")) |> Enum.sort()
  @template_paths Path.wildcard(Path.join(@project_root, "templates/*.md")) |> Enum.sort()
  @asset_paths [@defaults_path | @prompt_paths ++ @template_paths]

  for path <- @asset_paths do
    @external_resource path
  end

  @assets Enum.reduce(@asset_paths, %{}, fn path, acc ->
            relative_path =
              path
              |> Path.relative_to(@project_root)
              |> Path.split()
              |> Path.join()

            Map.put(acc, relative_path, File.read!(path))
          end)

  @spec fetch(String.t()) :: {:ok, String.t()} | :error
  def fetch(path) when is_binary(path) do
    case Map.fetch(@assets, normalize(path)) do
      {:ok, content} -> {:ok, content}
      :error -> :error
    end
  end

  defp normalize(path) do
    path
    |> String.trim_leading("./")
    |> Path.split()
    |> Path.join()
  end
end
