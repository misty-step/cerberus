defmodule Cerberus.Command do
  @moduledoc """
  Top-level CLI command router for the packaged `cerberus` executable.
  """

  @retired_commands ~w(init start server migrate)
  @success_exit_code 0
  @error_exit_code 1

  @type completed_result :: %{output: String.t(), exit_code: non_neg_integer()}
  @type failed_result :: %{message: String.t(), exit_code: pos_integer()}

  @spec execute([String.t()], keyword()) :: {:ok, completed_result()} | {:error, failed_result()}
  def execute(argv, opts \\ [])

  def execute([], _opts), do: {:ok, %{output: help(), exit_code: @success_exit_code}}
  def execute(["--help"], _opts), do: {:ok, %{output: help(), exit_code: @success_exit_code}}
  def execute(["-h"], _opts), do: {:ok, %{output: help(), exit_code: @success_exit_code}}
  def execute(["help"], _opts), do: {:ok, %{output: help(), exit_code: @success_exit_code}}

  def execute(["review" | rest], opts) do
    Application.load(:cerberus_elixir)
    Cerberus.CLI.execute(rest, opts)
  end

  def execute([command | _rest], _opts) when command in @retired_commands do
    {:error,
     %{
       message:
         "Command `#{command}` has been retired. Cerberus is CLI-only.\n\n#{Cerberus.CLI.usage()}",
       exit_code: @error_exit_code
     }}
  end

  def execute([command | _rest], _opts) do
    {:error,
     %{
       message: "Unknown command `#{command}`.\n\n#{help()}",
       exit_code: @error_exit_code
     }}
  end

  @spec main([String.t()], keyword()) :: :ok | {:error, String.t()}
  def main(argv \\ System.argv(), opts \\ []) do
    case execute(argv, opts) do
      {:ok, %{output: output, exit_code: exit_code}} ->
        print_stdout(output)
        maybe_halt(exit_code, opts)
        :ok

      {:error, %{message: message, exit_code: exit_code}} ->
        IO.puts(:stderr, message)
        maybe_halt(exit_code, opts)
        {:error, message}
    end
  end

  @spec help() :: String.t()
  def help do
    """
    Usage:
      cerberus review --repo <path> --base <ref> --head <ref> [--format json|text]

    Commands:
      review    Review a local repository ref range
    """
    |> String.trim_trailing()
  end

  defp print_stdout(output) do
    if String.ends_with?(output, "\n") do
      IO.write(output)
    else
      IO.puts(output)
    end
  end

  defp maybe_halt(code, opts) do
    if Keyword.get(opts, :halt, true) do
      System.halt(code)
    else
      :ok
    end
  end
end
