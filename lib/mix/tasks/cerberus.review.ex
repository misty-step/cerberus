defmodule Mix.Tasks.Cerberus.Review do
  use Mix.Task

  @shortdoc "Review a local repository ref range with Cerberus"

  @impl true
  def run(args) do
    Application.load(:cerberus_elixir)

    cli_opts = Application.get_env(:cerberus_elixir, :cli_overrides, [])
    cli_opts = Keyword.put_new(cli_opts, :halt, Mix.env() != :test)

    case Cerberus.CLI.execute(args, cli_opts) do
      {:ok, %{output: output, exit_code: exit_code}} ->
        Mix.shell().info(output)
        maybe_halt(exit_code, cli_opts)

      {:error, %{message: message, exit_code: exit_code}} ->
        Mix.shell().error(message)
        maybe_halt(exit_code, cli_opts)
    end
  end

  defp maybe_halt(code, cli_opts) do
    if Keyword.get(cli_opts, :halt, true) do
      System.halt(code)
    else
      :ok
    end
  end
end
