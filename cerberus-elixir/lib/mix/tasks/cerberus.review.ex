defmodule Mix.Tasks.Cerberus.Review do
  use Mix.Task

  @shortdoc "Review a local repository ref range with Cerberus"

  @impl true
  def run(args) do
    Application.load(:cerberus_elixir)

    cli_opts = Application.get_env(:cerberus_elixir, :cli_overrides, [])

    case Cerberus.CLI.run(args, cli_opts) do
      {:ok, output} ->
        Mix.shell().info(output)

      {:error, {message, 0}} ->
        Mix.shell().info(message)

      {:error, {message, _code}} ->
        Mix.raise(message)
    end
  end
end
