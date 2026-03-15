defmodule Cerberus.Router do
  @moduledoc """
  PR router: classifies PRs and selects the minimum effective reviewer panel.

  Reads personas and routing rules from `Cerberus.Config`. Uses an LLM
  (OpenRouter) for intelligent panel selection with deterministic fallback
  on any failure.

  ## Public API

      Cerberus.Router.route(diff_text)
      # => {:ok, %{panel: [...], reserves: [...], model_tier: :standard, ...}}
  """

  use GenServer
  require Logger

  @openrouter_url "https://openrouter.ai/api/v1/chat/completions"
  @default_router_model "openrouter/google/gemini-3-flash-preview"

  @doc_extensions MapSet.new(~w(.md .mdx .rst .txt .adoc .asciidoc .org))
  @security_hints MapSet.new(~w(auth security permission permissions oauth jwt api route router))

  # --- Client API ---

  def start_link(opts \\ []) do
    {name, opts} = Keyword.pop(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Route a PR diff to the minimum effective reviewer panel.

  Returns `{:ok, result}` where result contains:
  - `:panel` — perspective strings for the primary panel
  - `:reserves` — perspective strings available for escalation
  - `:model_tier` — `:flash | :standard | :pro`
  - `:size_bucket` — `:small | :medium | :large | :xlarge`
  - `:routing_used` — whether LLM routing succeeded
  """
  def route(diff_text, opts \\ [], server \\ __MODULE__) do
    GenServer.call(server, {:route, diff_text, opts}, 60_000)
  end

  # --- GenServer Callbacks ---

  @impl true
  def init(opts) do
    config_server = Keyword.get(opts, :config_server, Cerberus.Config)
    call_llm = Keyword.get(opts, :call_llm, &default_call_llm/1)
    {:ok, %{config_server: config_server, call_llm: call_llm}}
  end

  @impl true
  def handle_call({:route, diff_text, opts}, _from, state) do
    result = do_route(diff_text, opts, state)
    {:reply, {:ok, result}, state}
  rescue
    e ->
      Logger.warning("Router crashed: #{Exception.message(e)}")
      {:reply, {:ok, crash_fallback(safe_parse_diff(diff_text))}, state}
  catch
    kind, reason ->
      Logger.warning("Router #{kind}: #{inspect(reason)}")
      {:reply, {:ok, crash_fallback(safe_parse_diff(diff_text))}, state}
  end

  # --- Routing Core ---

  defp do_route(diff_text, opts, state) do
    personas = Cerberus.Config.personas(state.config_server)
    routing = Cerberus.Config.routing(state.config_server)

    summary = parse_diff(diff_text)
    size_bucket = classify_size(summary)
    model_tier = classify_model_tier(summary)

    all_perspectives = Enum.map(personas, &Atom.to_string(&1.perspective))
    name_to_perspective = Map.new(personas, &{&1.name, Atom.to_string(&1.perspective)})
    required = required_perspectives(routing, name_to_perspective, summary.code_changed)
    panel_size = max(min(routing.panel_size, length(personas)), length(required))
    metadata = opts |> Keyword.get(:metadata, %{}) |> normalize_metadata()
    router_model = non_empty_string(routing[:model], @default_router_model)

    {panel, routing_used} =
      if Map.get(routing, :enabled, true) do
        try_llm_routing(state.call_llm, personas, summary, panel_size, required, all_perspectives, metadata, router_model)
      else
        {[], false}
      end

    {panel, routing_used} =
      if panel == [] do
        {build_fallback_panel(routing, name_to_perspective, all_perspectives, panel_size, summary.code_changed), false}
      else
        {panel, routing_used}
      end

    reserves = Enum.reject(all_perspectives, &(&1 in panel))

    %{
      panel: panel,
      reserves: reserves,
      model_tier: model_tier,
      size_bucket: size_bucket,
      routing_used: routing_used
    }
  end

  # --- Diff Parsing ---

  @doc "Parse a unified diff string into structured file-level stats."
  def parse_diff(nil), do: empty_summary()
  def parse_diff(""), do: empty_summary()

  def parse_diff(diff_text) when is_binary(diff_text) do
    {files, _current} =
      diff_text
      |> String.split("\n")
      |> Enum.reduce({%{}, nil}, &reduce_diff_line/2)

    file_list =
      files
      |> Enum.sort_by(fn {path, _} -> path end)
      |> Enum.map(fn {_path, record} ->
        ext = Path.extname(record.path) |> String.downcase()
        {is_doc, is_test, is_code} = classify_file(record.path)
        %{record | extension: ext, is_doc: is_doc, is_test: is_test, is_code: is_code}
      end)

    total_add = Enum.sum_by(file_list, & &1.additions)
    total_del = Enum.sum_by(file_list, & &1.deletions)

    %{
      files: file_list,
      total_additions: total_add,
      total_deletions: total_del,
      total_changed_lines: total_add + total_del,
      total_files: length(file_list),
      extensions: file_list |> Enum.map(& &1.extension) |> Enum.frequencies(),
      doc_files: Enum.count(file_list, & &1.is_doc),
      test_files: Enum.count(file_list, & &1.is_test),
      code_files: Enum.count(file_list, & &1.is_code),
      code_changed: Enum.any?(file_list, & &1.is_code)
    }
  end

  defp reduce_diff_line(line, {files, current}) do
    cond do
      String.starts_with?(line, "diff --git ") ->
        case parse_diff_header(line) do
          {:ok, path} -> {Map.put_new(files, path, new_file_record(path)), path}
          :error -> {files, current}
        end

      String.starts_with?(line, "+++ ") and current != nil ->
        case extract_b_path(line) do
          {:ok, "/dev/null"} ->
            {files, current}

          {:ok, new_path} when new_path != current ->
            record = Map.get(files, current, new_file_record(new_path))
            {files |> Map.delete(current) |> Map.put(new_path, %{record | path: new_path}), new_path}

          _ ->
            {files, current}
        end

      String.starts_with?(line, "+") and not String.starts_with?(line, "+++ ") and current != nil ->
        {Map.update!(files, current, &%{&1 | additions: &1.additions + 1}), current}

      String.starts_with?(line, "-") and not String.starts_with?(line, "--- ") and current != nil ->
        {Map.update!(files, current, &%{&1 | deletions: &1.deletions + 1}), current}

      true ->
        {files, current}
    end
  end

  # --- Classification ---

  @doc "Classify a file path as {is_doc, is_test, is_code}."
  def classify_file(path) do
    normalized = String.downcase(path) |> String.trim_leading("/")
    ext = Path.extname(normalized)
    name = Path.basename(normalized)

    is_doc =
      MapSet.member?(@doc_extensions, ext) or
        String.starts_with?(normalized, "docs/") or
        String.starts_with?(normalized, "doc/") or
        name in ~w(readme readme.md changelog.md license contributing.md)

    is_test =
      String.contains?(normalized, "/test/") or
        String.contains?(normalized, "/tests/") or
        String.starts_with?(normalized, "test/") or
        String.starts_with?(normalized, "tests/") or
        String.starts_with?(name, "test_") or
        String.ends_with?(name, "_test.py") or
        String.ends_with?(name, "_test.exs") or
        String.ends_with?(name, "_test.ex") or
        String.contains?(name, ".test.") or
        String.contains?(name, ".spec.")

    cond do
      is_doc -> {true, false, false}
      is_test -> {false, true, false}
      true -> {false, false, true}
    end
  end

  @doc "Classify PR size bucket from diff summary."
  def classify_size(%{total_changed_lines: lines}) do
    cond do
      lines <= 50 -> :small
      lines <= 200 -> :medium
      lines <= 500 -> :large
      true -> :xlarge
    end
  end

  @doc "Classify model tier from diff summary."
  def classify_model_tier(%{
        total_changed_lines: lines,
        code_files: code_files,
        test_files: test_files,
        doc_files: doc_files,
        files: files
      }) do
    has_security_hint =
      Enum.any?(files, fn f ->
        path = String.downcase(f.path)
        Enum.any?(@security_hints, &String.contains?(path, &1))
      end)

    cond do
      lines <= 50 and code_files == 0 and test_files + doc_files > 0 -> :flash
      lines >= 300 or has_security_hint -> :pro
      true -> :standard
    end
  end

  # --- Panel Building ---

  @doc false
  def required_perspectives(routing, name_to_perspective, code_changed?) do
    always = resolve_names(routing.always_include, name_to_perspective)

    if code_changed? do
      code_req = resolve_names(Map.get(routing, :include_if_code_changed, []), name_to_perspective)
      Enum.uniq(always ++ code_req)
    else
      always
    end
  end

  @doc false
  def build_fallback_panel(routing, name_to_perspective, all_perspectives, panel_size, code_changed?) do
    required = required_perspectives(routing, name_to_perspective, code_changed?)
    fallback_order = resolve_names(routing.fallback_panel, name_to_perspective)
    required_set = MapSet.new(required)

    skip_when_no_code =
      if code_changed? do
        MapSet.new()
      else
        routing
        |> Map.get(:include_if_code_changed, [])
        |> resolve_names(name_to_perspective)
        |> MapSet.new()
      end

    # Start with required, extend from fallback order, then remaining perspectives
    pool = fallback_order ++ all_perspectives
    seen = MapSet.new(required)

    extras =
      Enum.reduce(pool, {[], seen}, fn p, {acc, seen_set} ->
        if MapSet.member?(seen_set, p) or
             (MapSet.member?(skip_when_no_code, p) and not MapSet.member?(required_set, p)) do
          {acc, seen_set}
        else
          {[p | acc], MapSet.put(seen_set, p)}
        end
      end)
      |> elem(0)
      |> Enum.reverse()

    (required ++ extras) |> Enum.take(panel_size)
  end

  # --- LLM Routing ---

  defp try_llm_routing(call_llm, personas, summary, panel_size, required, all_perspectives, metadata, router_model) do
    prompt = build_prompt(personas, summary, panel_size, required, metadata)

    params = %{
      model: router_model,
      prompt: prompt,
      panel_size: panel_size,
      all_perspectives: all_perspectives
    }

    try do
      case call_llm.(params) do
        {:ok, panel} when is_list(panel) ->
          validated = validate_panel(panel, required, all_perspectives, panel_size)
          if validated != [], do: {validated, true}, else: {[], false}

        {:error, reason} ->
          Logger.warning("Router LLM call failed: #{inspect(reason)}")
          {[], false}

        other ->
          Logger.warning("Router LLM returned unexpected payload: #{inspect(other)}")
          {[], false}
      end
    rescue
      e ->
        Logger.warning("Router LLM call raised: #{Exception.message(e)}")
        {[], false}
    catch
      kind, reason ->
        Logger.warning("Router LLM call #{kind}: #{inspect(reason)}")
        {[], false}
    end
  end

  defp build_prompt(personas, summary, panel_size, required, metadata) do
    required_text = if required == [], do: "(none)", else: Enum.join(required, ", ")

    ext_text =
      summary.extensions
      |> Enum.map(fn {k, v} -> "#{k}:#{v}" end)
      |> Enum.join(", ")

    ext_text = if ext_text == "", do: "(none)", else: ext_text

    repo = metadata |> Map.get(:repo, "unknown") |> sanitize_prompt_value()
    ref = metadata |> Map.get(:ref, "unknown") |> sanitize_prompt_value()
    event = metadata |> Map.get(:event, "unknown") |> sanitize_prompt_value()

    bench_rows =
      Enum.map(personas, fn p ->
        focus = p.description || Atom.to_string(p.perspective)
        "| #{p.name} | #{p.perspective} | #{focus} |"
      end)

    file_rows =
      summary.files
      |> Enum.take(250)
      |> Enum.map(fn f ->
        tags =
          [if(f.is_code, do: "code"), if(f.is_test, do: "test"), if(f.is_doc, do: "doc")]
          |> Enum.reject(&is_nil/1)

        tag_text = if tags == [], do: "unknown", else: Enum.join(tags, ",")
        safe_path = sanitize_prompt_value(f.path)
        "- #{safe_path} (+#{f.additions}, -#{f.deletions}) [ext=#{f.extension} type=#{tag_text}]"
      end)

    file_rows = if file_rows == [], do: ["- (no changed files parsed)"], else: file_rows

    """
    ## Role
    You are Cerberus's reviewer router.

    ## Objective
    Choose the smallest useful reviewer subset for this pull request, capped at exactly #{panel_size} reviewers.

    ## Bench
    | Codename | Perspective | Focus |
    |----------|-------------|-------|
    #{Enum.join(bench_rows, "\n")}

    ## MUST
    - Select EXACTLY #{panel_size} perspectives
    - Include these required perspectives when applicable: #{required_text}
    - Use the remaining slots on the reviewers most likely to change the verdict

    ## MUST NOT
    - Do not explain your choice
    - Do not invent perspectives that are not in the bench

    ## PR Metadata
    - Repository: #{repo}
    - Ref: #{ref}
    - Event: #{event}
    - Files changed: #{summary.total_files}
    - Lines added: #{summary.total_additions}
    - Lines removed: #{summary.total_deletions}
    - Total changed lines: #{summary.total_changed_lines}
    - Code files: #{summary.code_files} | Test files: #{summary.test_files} | Doc files: #{summary.doc_files}
    - Extension histogram: #{ext_text}

    ## Changed Files
    #{Enum.join(file_rows, "\n")}

    ## Output Contract
    Respond with ONLY a JSON array of exactly #{panel_size} perspective strings.
    Example: ["correctness","security","architecture","testing"]
    """
  end

  defp validate_panel(panel, required, all_perspectives, panel_size) do
    normalized =
      panel
      |> Enum.map(&String.downcase(to_string(&1)))
      |> Enum.uniq()

    valid_set = MapSet.new(all_perspectives)
    required_set = MapSet.new(required)
    panel_set = MapSet.new(normalized)

    cond do
      length(normalized) != panel_size -> []
      not MapSet.subset?(required_set, panel_set) -> []
      not MapSet.subset?(panel_set, valid_set) -> []
      true -> normalized
    end
  end

  # --- LLM Transport ---

  defp default_call_llm(params) do
    api_key =
      System.get_env("CERBERUS_API_KEY") ||
        System.get_env("CERBERUS_OPENROUTER_API_KEY") ||
        System.get_env("OPENROUTER_API_KEY")

    if is_nil(api_key) or api_key == "" do
      {:error, :no_api_key}
    else
      do_call_openrouter(api_key, params)
    end
  end

  defp do_call_openrouter(api_key, params) do
    payload = %{
      model: params.model,
      temperature: 0.1,
      max_tokens: 400,
      messages: [
        %{
          role: "system",
          content:
            "You are a senior code-review routing lead. " <>
              "Pick the smallest reviewer subset that preserves correctness and safety. " <>
              "Follow the output contract exactly."
        },
        %{role: "user", content: params.prompt}
      ],
      response_format: %{
        type: "json_schema",
        json_schema: %{
          name: "cerberus_panel",
          strict: true,
          schema: %{
            type: "object",
            properties: %{
              panel: %{
                type: "array",
                items: %{type: "string"},
                minItems: params.panel_size,
                maxItems: params.panel_size
              }
            },
            required: ["panel"],
            additionalProperties: false
          }
        }
      }
    }

    case Req.post(@openrouter_url,
           json: payload,
           headers: [
             {"authorization", "Bearer #{api_key}"},
             {"user-agent", "cerberus-router/1.0"},
             {"http-referer", "https://github.com/misty-step/cerberus"},
             {"x-title", "Cerberus Router"}
           ],
           receive_timeout: 30_000
         ) do
      {:ok, %{status: 200, body: body}} ->
        parse_llm_response(body)

      {:ok, %{status: status, body: body}} ->
        {:error, {:http_error, status, inspect(body)}}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp parse_llm_response(body) when is_map(body) do
    with choices when is_list(choices) and choices != [] <- body["choices"],
         message when is_map(message) <- hd(choices)["message"],
         content when is_binary(content) <- message["content"],
         {:ok, parsed} <- Jason.decode(content),
         panel when is_list(panel) <- extract_panel(parsed) do
      {:ok, Enum.map(panel, &to_string/1)}
    else
      _ -> {:error, :invalid_response}
    end
  end

  defp parse_llm_response(_), do: {:error, :invalid_response}

  defp extract_panel(%{"panel" => panel}) when is_list(panel), do: panel
  defp extract_panel(list) when is_list(list), do: list
  defp extract_panel(_), do: nil

  # --- Helpers ---

  defp resolve_names(names, name_to_perspective) do
    names
    |> Enum.map(&Map.get(name_to_perspective, &1))
    |> Enum.reject(&is_nil/1)
  end

  defp parse_diff_header(line) do
    case String.split(line) do
      ["diff", "--git", _a, b | _] ->
        path = if String.starts_with?(b, "b/"), do: String.slice(b, 2..-1//1), else: b
        {:ok, path}

      _ ->
        :error
    end
  end

  defp extract_b_path(line) do
    path = String.slice(line, 4..-1//1) |> String.trim()

    if String.starts_with?(path, "b/") do
      {:ok, String.slice(path, 2..-1//1)}
    else
      {:ok, path}
    end
  end

  defp new_file_record(path) do
    %{
      path: path,
      additions: 0,
      deletions: 0,
      extension: "",
      is_doc: false,
      is_test: false,
      is_code: false
    }
  end

  defp empty_summary do
    %{
      files: [],
      total_additions: 0,
      total_deletions: 0,
      total_changed_lines: 0,
      total_files: 0,
      extensions: %{},
      doc_files: 0,
      test_files: 0,
      code_files: 0,
      code_changed: false
    }
  end

  @default_crash_panel ~w(correctness security architecture testing)
  defp crash_fallback(summary) do
    %{
      panel: @default_crash_panel,
      reserves: ~w(maintainability resilience),
      model_tier: classify_model_tier_safe(summary),
      size_bucket: classify_size(summary),
      routing_used: false
    }
  end

  defp classify_model_tier_safe(summary) do
    classify_model_tier(summary)
  rescue
    _ -> :standard
  end

  defp safe_parse_diff(text) when is_binary(text) do
    parse_diff(text)
  rescue
    _ -> empty_summary()
  end

  defp safe_parse_diff(_), do: empty_summary()

  defp non_empty_string(val, _default) when is_binary(val) and val != "", do: val
  defp non_empty_string(_, default), do: default

  defp normalize_metadata(m) when is_map(m), do: m
  defp normalize_metadata(m) when is_list(m), do: Map.new(m)
  defp normalize_metadata(_), do: %{}

  defp sanitize_prompt_value(val) when is_binary(val) do
    val
    |> String.replace(~r/[\n\r]/, " ")
    |> String.slice(0, 200)
  end

  defp sanitize_prompt_value(_), do: "unknown"
end
