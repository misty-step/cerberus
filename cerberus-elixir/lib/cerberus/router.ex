defmodule Cerberus.Router do
  @moduledoc """
  Review planner/router: classifies a change range and selects the smallest
  useful reviewer team from the active bench.

  The planner inspects diff shape plus repository-local context, asks the
  configured planner model to choose within the eligible bench, and falls back
  deterministically whenever inference fails or returns invalid output.
  """

  use GenServer
  require Logger

  @openrouter_url "https://openrouter.ai/api/v1/chat/completions"
  @default_router_model "openrouter/google/gemini-3-flash-preview"
  @fallback_policy "bench_priority_v1"

  @doc_extensions MapSet.new(~w(.md .mdx .rst .txt .adoc .asciidoc .org))
  @security_hints MapSet.new(~w(auth security permission permissions oauth jwt api route router))
  @contract_hints MapSet.new(
                    ~w(openapi graphql proto schema contract contracts cli command public interface)
                  )
  @config_extensions MapSet.new(~w(.yml .yaml .json .toml .ini .cfg .conf .env))
  @config_names MapSet.new(~w(
                    mix.exs
                    mix.lock
                    package.json
                    package-lock.json
                    yarn.lock
                    pnpm-lock.yaml
                    Cargo.toml
                    Cargo.lock
                    go.mod
                    go.sum
                    pyproject.toml
                    Pipfile
                    Pipfile.lock
                    Gemfile
                    Gemfile.lock
                    Dockerfile
                    docker-compose.yml
                    docker-compose.yaml
                  ))
  @public_contract_globs [
    "priv/openapi/**/*",
    "openapi/**/*",
    "api/**/*",
    "graphql/**/*",
    "proto/**/*",
    "schema/**/*",
    "contracts/**/*",
    "lib/**/*_web/router.ex"
  ]
  @security_repo_globs [
    "lib/**/auth/**/*",
    "lib/**/security/**/*",
    "lib/**/permissions/**/*",
    "lib/**/policy/**/*",
    "lib/**/oauth/**/*",
    "lib/**/jwt/**/*",
    "src/**/auth/**/*",
    "src/**/security/**/*",
    "app/**/auth/**/*"
  ]
  @config_repo_globs [
    "config/**/*",
    ".github/workflows/**/*",
    "mix.exs",
    "package.json",
    "Cargo.toml",
    "pyproject.toml"
  ]
  @default_crash_panel ~w(trace guard atlas proof)

  # --- Client API ---

  def start_link(opts \\ []) do
    {name, opts} = Keyword.pop(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Route a PR diff to the minimum effective reviewer panel.

  Returns `{:ok, result}` where result contains:
  - `:panel` — reviewer ids for the selected team
  - `:reserves` — active-bench reviewer ids not selected for the run
  - `:model_tier` — `:flash | :standard | :pro`
  - `:size_bucket` — `:small | :medium | :large | :xlarge`
  - `:routing_used` — whether LLM routing succeeded
  - `:planner_trace` — deterministic planner evidence for validation and replay
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
      {:reply, {:ok, crash_fallback(diff_text, opts, state, "router_exception")}, state}
  catch
    kind, reason ->
      Logger.warning("Router #{kind}: #{inspect(reason)}")
      fallback_reason = "router_#{kind}:#{inspect(reason)}"
      {:reply, {:ok, crash_fallback(diff_text, opts, state, fallback_reason)}, state}
  end

  # --- Routing Core ---

  defp do_route(diff_text, opts, state) do
    personas = Cerberus.Config.personas(state.config_server)
    routing = Cerberus.Config.routing(state.config_server)
    metadata = opts |> Keyword.get(:metadata, %{}) |> normalize_metadata()
    summary = parse_diff(diff_text)

    required = required_reviewers(routing, summary.code_changed)
    repo_context = inspect_repo_context(metadata)
    diff_classification = classify_diff(summary, repo_context)
    size_bucket = classify_size(summary)
    model_tier = determine_model_tier(summary, diff_classification, repo_context)
    all_reviewers = Enum.map(personas, & &1.id)

    panel_size =
      determine_panel_size(routing, personas, required, diff_classification, repo_context)

    eligible_bench =
      eligible_bench(personas, routing, required, panel_size, diff_classification, repo_context)

    fallback_panel =
      build_ranked_fallback_panel(
        personas,
        routing,
        required,
        eligible_bench,
        panel_size,
        diff_classification,
        repo_context
      )

    router_model = non_empty_string(routing[:model], @default_router_model)

    {panel, routing_used, fallback_reason} =
      cond do
        panel_size == 0 ->
          {[], false, "empty_bench"}

        not Map.get(routing, :enabled, true) ->
          {fallback_panel, false, "routing_disabled"}

        true ->
          case try_llm_routing(
                 state.call_llm,
                 personas,
                 summary,
                 panel_size,
                 required,
                 all_reviewers,
                 eligible_bench,
                 metadata,
                 repo_context,
                 diff_classification,
                 router_model,
                 fallback_panel,
                 model_tier,
                 size_bucket
               ) do
            {:ok, llm_panel} ->
              {llm_panel, true, nil}

            {:error, reason} ->
              {fallback_panel, false, reason}
          end
      end

    reserves = Enum.reject(all_reviewers, &(&1 in panel))

    %{
      panel: panel,
      reserves: reserves,
      model_tier: model_tier,
      size_bucket: size_bucket,
      routing_used: routing_used,
      planner_trace:
        planner_trace(
          summary,
          diff_classification,
          repo_context,
          eligible_bench,
          panel,
          model_tier,
          size_bucket,
          router_model,
          required,
          routing_used,
          fallback_reason
        )
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

            {files |> Map.delete(current) |> Map.put(new_path, %{record | path: new_path}),
             new_path}

          _ ->
            {files, current}
        end

      String.starts_with?(line, "+") and not String.starts_with?(line, "+++ ") and
          current != nil ->
        {Map.update!(files, current, &%{&1 | additions: &1.additions + 1}), current}

      String.starts_with?(line, "-") and not String.starts_with?(line, "--- ") and
          current != nil ->
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
  def classify_model_tier(summary) do
    determine_model_tier(
      summary,
      classify_diff(summary, default_repo_context()),
      default_repo_context()
    )
  end

  # --- Panel Building ---

  @doc false
  def required_reviewers(routing, code_changed?) do
    always = routing.always_include

    if code_changed? do
      Enum.uniq(always ++ Map.get(routing, :include_if_code_changed, []))
    else
      always
    end
  end

  @doc false
  def build_fallback_panel(routing, all_reviewers, panel_size, code_changed?) do
    required = required_reviewers(routing, code_changed?)
    fallback_order = routing.fallback_panel
    required_set = MapSet.new(required)

    skip_when_no_code =
      if code_changed? do
        MapSet.new()
      else
        routing
        |> Map.get(:include_if_code_changed, [])
        |> MapSet.new()
      end

    pool = fallback_order ++ all_reviewers
    seen = MapSet.new(required)

    extras =
      Enum.reduce(pool, {[], seen}, fn reviewer_id, {acc, seen_set} ->
        if MapSet.member?(seen_set, reviewer_id) or
             (MapSet.member?(skip_when_no_code, reviewer_id) and
                not MapSet.member?(required_set, reviewer_id)) do
          {acc, seen_set}
        else
          {[reviewer_id | acc], MapSet.put(seen_set, reviewer_id)}
        end
      end)
      |> elem(0)
      |> Enum.reverse()

    (required ++ extras) |> Enum.take(panel_size)
  end

  defp build_ranked_fallback_panel(
         personas,
         routing,
         required,
         eligible_reviewers,
         panel_size,
         diff_classification,
         repo_context
       ) do
    persona_by_id = Map.new(personas, &{&1.id, &1})
    active_order = personas |> Enum.map(& &1.id) |> Enum.with_index() |> Map.new()
    fallback_order = routing.fallback_panel |> Enum.with_index() |> Map.new()
    eligible_set = MapSet.new(eligible_reviewers)
    required_panel = Enum.filter(required, &MapSet.member?(eligible_set, &1))

    extras =
      eligible_reviewers
      |> Enum.reject(&(&1 in required_panel))
      |> Enum.sort_by(fn reviewer_id ->
        persona = Map.fetch!(persona_by_id, reviewer_id)

        {
          -reviewer_score(persona, diff_classification, repo_context),
          Map.get(fallback_order, reviewer_id, 999),
          Map.get(active_order, reviewer_id, 999),
          reviewer_id
        }
      end)

    (required_panel ++ extras) |> Enum.take(panel_size)
  end

  # --- LLM Routing ---

  defp try_llm_routing(
         call_llm,
         personas,
         summary,
         panel_size,
         required,
         all_reviewers,
         eligible_reviewers,
         metadata,
         repo_context,
         diff_classification,
         router_model,
         suggested_panel,
         model_tier,
         size_bucket
       ) do
    prompt =
      build_prompt(
        personas,
        summary,
        panel_size,
        required,
        eligible_reviewers,
        metadata,
        repo_context,
        diff_classification
      )

    params = %{
      model: router_model,
      provider: "openrouter",
      prompt: prompt,
      panel_size: panel_size,
      all_reviewers: all_reviewers,
      eligible_reviewers: eligible_reviewers,
      required_reviewers: required,
      suggested_panel: suggested_panel,
      diff_classification: diff_classification,
      repo_context: repo_context,
      model_tier: model_tier,
      size_bucket: size_bucket
    }

    try do
      case call_llm.(params) do
        {:ok, panel} when is_list(panel) ->
          case validate_panel(panel, required, eligible_reviewers, panel_size) do
            [] -> {:error, "invalid_panel"}
            validated -> {:ok, validated}
          end

        {:error, reason} ->
          Logger.warning("Router LLM call failed: #{inspect(reason)}")
          {:error, "llm_error"}

        other ->
          Logger.warning("Router LLM returned unexpected payload: #{inspect(other)}")
          {:error, "invalid_response"}
      end
    rescue
      e ->
        Logger.warning("Router LLM call raised: #{Exception.message(e)}")
        {:error, "llm_exception"}
    catch
      kind, reason ->
        Logger.warning("Router LLM call #{kind}: #{inspect(reason)}")
        {:error, "llm_exception"}
    end
  end

  defp build_prompt(
         personas,
         summary,
         panel_size,
         required,
         eligible_reviewers,
         metadata,
         repo_context,
         diff_classification
       ) do
    required_text = if required == [], do: "(none)", else: Enum.join(required, ", ")

    eligible_text =
      if eligible_reviewers == [], do: "(none)", else: Enum.join(eligible_reviewers, ", ")

    ext_text =
      summary.extensions
      |> Enum.map(fn {key, value} -> "#{key}:#{value}" end)
      |> Enum.join(", ")
      |> then(fn
        "" -> "(none)"
        value -> value
      end)

    repo = metadata |> Map.get(:repo, "unknown") |> sanitize_prompt_value()
    ref = metadata |> Map.get(:ref, "unknown") |> sanitize_prompt_value()
    event = metadata |> Map.get(:event, "unknown") |> sanitize_prompt_value()

    bench_rows =
      personas
      |> Enum.filter(&(&1.id in eligible_reviewers))
      |> Enum.map(fn persona ->
        focus = persona.description || Atom.to_string(persona.perspective)
        "| #{persona.id} | #{persona.perspective} | #{focus} |"
      end)
      |> then(fn
        [] -> ["| (none) | n/a | n/a |"]
        rows -> rows
      end)

    file_rows =
      summary.files
      |> Enum.take(250)
      |> Enum.map(fn file ->
        tags =
          [if(file.is_code, do: "code"), if(file.is_test, do: "test"), if(file.is_doc, do: "doc")]
          |> Enum.reject(&is_nil/1)
          |> Enum.join(",")
          |> then(fn
            "" -> "unknown"
            value -> value
          end)

        safe_path = sanitize_prompt_value(file.path)

        "- #{safe_path} (+#{file.additions}, -#{file.deletions}) [ext=#{file.extension} type=#{tags}]"
      end)
      |> then(fn
        [] -> ["- (no changed files parsed)"]
        rows -> rows
      end)

    """
    ## Role
    You are Cerberus's review planner.

    ## Objective
    Choose the smallest useful reviewer subset for this change range, capped at exactly #{panel_size} reviewers.

    ## Eligible Bench
    | Reviewer ID | Perspective | Focus |
    |-------------|-------------|-------|
    #{Enum.join(bench_rows, "\n")}

    ## MUST
    - Select EXACTLY #{panel_size} reviewer ids
    - Include these required reviewer ids when applicable: #{required_text}
    - Select ONLY from this eligible bench: #{eligible_text}
    - Use the remaining slots on the reviewers most likely to change the verdict

    ## MUST NOT
    - Do not explain your choice
    - Do not invent reviewer ids that are not in the eligible bench

    ## Change Metadata
    - Repository: #{repo}
    - Ref: #{ref}
    - Event: #{event}
    - Files changed: #{summary.total_files}
    - Lines added: #{summary.total_additions}
    - Lines removed: #{summary.total_deletions}
    - Total changed lines: #{summary.total_changed_lines}
    - Code files: #{summary.code_files} | Test files: #{summary.test_files} | Doc files: #{summary.doc_files}
    - Extension histogram: #{ext_text}
    - Repo context signals: #{repo_signal_text(repo_context)}
    - Deterministic diff classification: #{classification_text(diff_classification)}

    ## Changed Files
    #{Enum.join(file_rows, "\n")}

    ## Output Contract
    Respond with ONLY a JSON array of exactly #{panel_size} reviewer id strings.
    Example: ["trace","guard","atlas","proof"]
    """
  end

  defp validate_panel(panel, required, eligible_reviewers, panel_size) do
    normalized =
      panel
      |> Enum.map(&String.downcase(to_string(&1)))
      |> Enum.uniq()

    valid_set = MapSet.new(eligible_reviewers)
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

  # --- Deterministic Planning ---

  defp determine_model_tier(summary, diff_classification, repo_context) do
    repo_sensitive =
      repo_context.signals.public_contract_surface or repo_context.signals.security_sensitive_repo

    cond do
      diff_classification.doc_only ->
        :flash

      diff_classification.test_only and not diff_classification.config_change ->
        :flash

      diff_classification.non_code_only and not diff_classification.config_change and
          summary.total_changed_lines <= 50 ->
        :flash

      summary.total_changed_lines >= 300 ->
        :pro

      diff_classification.risky_change or diff_classification.contract_surface_change ->
        :pro

      repo_sensitive and summary.code_changed ->
        :pro

      diff_classification.broad_change and summary.total_changed_lines >= 40 ->
        :pro

      true ->
        :standard
    end
  end

  defp determine_panel_size(routing, personas, required, diff_classification, repo_context) do
    max_size = min(routing.panel_size, length(personas))

    if max_size == 0 do
      0
    else
      repo_sensitive =
        repo_context.signals.public_contract_surface or
          repo_context.signals.security_sensitive_repo

      desired =
        cond do
          diff_classification.doc_only -> 1
          diff_classification.test_only -> 2
          diff_classification.non_code_only and diff_classification.config_change -> 3
          diff_classification.non_code_only -> 2
          true -> 3
        end

      desired =
        if diff_classification.risky_change or diff_classification.contract_surface_change or
             repo_sensitive do
          max(desired, 4)
        else
          desired
        end

      desired =
        if diff_classification.broad_change do
          max(desired, 4)
        else
          desired
        end

      min(max(desired, length(required)), max_size)
    end
  end

  defp classify_diff(summary, repo_context) do
    tags = Enum.map(summary.files, &file_tags(&1.path))
    surface_buckets = tags |> Enum.map(& &1.surface_bucket) |> Enum.uniq() |> Enum.sort()
    config_change = Enum.any?(tags, & &1.config)
    ci_change = Enum.any?(tags, & &1.ci)
    cli_change = Enum.any?(tags, & &1.cli)
    security_paths = Enum.any?(tags, & &1.security)
    contract_paths = Enum.any?(tags, & &1.contract)

    doc_only =
      summary.doc_files > 0 and summary.code_files == 0 and summary.test_files == 0 and
        not config_change

    test_only =
      summary.test_files > 0 and summary.code_files == 0 and summary.doc_files == 0 and
        not config_change

    non_code_only = summary.code_files == 0

    broad_change =
      length(surface_buckets) >= 3 or
        (length(surface_buckets) >= 2 and summary.total_files >= 4) or
        (config_change and summary.code_changed and length(surface_buckets) >= 2)

    contract_surface_change =
      contract_paths or (repo_context.signals.public_contract_surface and summary.code_changed)

    risky_change =
      security_paths or cli_change or contract_surface_change or
        (config_change and summary.code_changed) or
        (repo_context.signals.security_sensitive_repo and summary.code_changed)

    %{
      doc_only: doc_only,
      test_only: test_only,
      non_code_only: non_code_only,
      config_change: config_change,
      ci_change: ci_change,
      cli_change: cli_change,
      contract_surface_change: contract_surface_change,
      risky_change: risky_change,
      broad_change: broad_change,
      surface_buckets: surface_buckets
    }
  end

  defp eligible_bench(personas, routing, required, panel_size, diff_classification, repo_context) do
    perspective_allowlist = eligible_perspectives(diff_classification, repo_context)
    all_reviewers = Enum.map(personas, & &1.id)

    base =
      personas
      |> Enum.filter(fn persona ->
        persona.id in required or
          is_nil(perspective_allowlist) or
          MapSet.member?(perspective_allowlist, persona.perspective)
      end)
      |> Enum.map(& &1.id)

    expanded =
      if length(base) >= panel_size do
        base
      else
        expand_eligible_bench(
          personas,
          routing,
          base,
          panel_size,
          diff_classification,
          repo_context
        )
      end

    expanded
    |> Enum.uniq()
    |> Enum.filter(&(&1 in all_reviewers))
  end

  defp eligible_perspectives(diff_classification, repo_context) do
    repo_sensitive =
      repo_context.signals.public_contract_surface or repo_context.signals.security_sensitive_repo

    cond do
      diff_classification.doc_only ->
        MapSet.new([:correctness, :maintainability])

      diff_classification.test_only ->
        MapSet.new([:correctness, :testing, :maintainability])

      diff_classification.non_code_only and diff_classification.config_change ->
        MapSet.new([:correctness, :architecture, :resilience])

      diff_classification.risky_change or diff_classification.contract_surface_change or
          diff_classification.broad_change ->
        nil

      repo_sensitive ->
        MapSet.new([:correctness, :security, :architecture, :testing])

      true ->
        MapSet.new([:correctness, :security, :architecture, :maintainability])
    end
  end

  defp expand_eligible_bench(
         personas,
         routing,
         current,
         panel_size,
         diff_classification,
         repo_context
       ) do
    current_set = MapSet.new(current)
    active_order = personas |> Enum.map(& &1.id) |> Enum.with_index() |> Map.new()
    fallback_order = routing.fallback_panel |> Enum.with_index() |> Map.new()

    extras =
      personas
      |> Enum.reject(&MapSet.member?(current_set, &1.id))
      |> Enum.sort_by(fn persona ->
        {
          -reviewer_score(persona, diff_classification, repo_context),
          Map.get(fallback_order, persona.id, 999),
          Map.get(active_order, persona.id, 999),
          persona.id
        }
      end)
      |> Enum.take(max(panel_size - length(current), 0))
      |> Enum.map(& &1.id)

    current ++ extras
  end

  defp reviewer_score(persona, diff_classification, repo_context) do
    repo_sensitive =
      repo_context.signals.public_contract_surface or repo_context.signals.security_sensitive_repo

    case persona.perspective do
      :correctness ->
        100

      :security ->
        cond do
          diff_classification.risky_change -> 95
          repo_context.signals.security_sensitive_repo -> 75
          diff_classification.contract_surface_change -> 70
          true -> 30
        end

      :architecture ->
        cond do
          diff_classification.broad_change -> 95
          diff_classification.contract_surface_change -> 85
          repo_context.signals.public_contract_surface -> 80
          diff_classification.config_change -> 60
          true -> 35
        end

      :testing ->
        cond do
          diff_classification.test_only -> 95
          diff_classification.risky_change -> 75
          diff_classification.contract_surface_change -> 70
          true -> 40
        end

      :maintainability ->
        cond do
          diff_classification.doc_only -> 95
          diff_classification.non_code_only -> 70
          diff_classification.broad_change -> 55
          true -> 45
        end

      :resilience ->
        cond do
          diff_classification.broad_change -> 80
          diff_classification.risky_change -> 75
          diff_classification.config_change -> 70
          repo_sensitive -> 65
          true -> 25
        end

      _ ->
        0
    end
  end

  defp inspect_repo_context(metadata) do
    case normalize_repo_root(Map.get(metadata, :repo)) do
      {:ok, repo_root} ->
        public_markers = repo_markers(repo_root, @public_contract_globs)
        security_markers = repo_markers(repo_root, @security_repo_globs)
        config_markers = repo_markers(repo_root, @config_repo_globs)

        %{
          available: true,
          repo_root: repo_root,
          signals: %{
            public_contract_surface: public_markers != [],
            security_sensitive_repo: security_markers != [],
            config_surface: config_markers != []
          },
          markers: %{
            public_contract_surface: public_markers,
            security_sensitive_repo: security_markers,
            config_surface: config_markers
          }
        }

      :error ->
        default_repo_context()
    end
  end

  defp normalize_repo_root(repo_root) when is_binary(repo_root) do
    expanded = Path.expand(repo_root)
    if File.dir?(expanded), do: {:ok, expanded}, else: :error
  end

  defp normalize_repo_root(_), do: :error

  defp default_repo_context do
    %{
      available: false,
      repo_root: nil,
      signals: %{
        public_contract_surface: false,
        security_sensitive_repo: false,
        config_surface: false
      },
      markers: %{
        public_contract_surface: [],
        security_sensitive_repo: [],
        config_surface: []
      }
    }
  end

  defp repo_markers(repo_root, patterns) do
    patterns
    |> Enum.flat_map(fn pattern ->
      Path.wildcard(Path.join(repo_root, pattern), match_dot: true)
    end)
    |> Enum.map(&Path.relative_to(&1, repo_root))
    |> Enum.uniq()
    |> Enum.sort()
    |> Enum.take(5)
  end

  defp planner_trace(
         summary,
         diff_classification,
         repo_context,
         eligible_bench,
         selected_team,
         model_tier,
         size_bucket,
         router_model,
         required_reviewers,
         routing_used,
         fallback_reason
       ) do
    %{
      diff_summary: %{
        total_files: summary.total_files,
        total_changed_lines: summary.total_changed_lines,
        total_additions: summary.total_additions,
        total_deletions: summary.total_deletions,
        code_files: summary.code_files,
        test_files: summary.test_files,
        doc_files: summary.doc_files,
        surface_count: length(diff_classification.surface_buckets),
        surface_buckets: diff_classification.surface_buckets
      },
      diff_classification: diff_classification,
      repo_context: repo_context,
      eligible_bench: eligible_bench,
      selected_team: selected_team,
      required_reviewers: required_reviewers,
      model_tier: Atom.to_string(model_tier),
      size_bucket: Atom.to_string(size_bucket),
      routing_used: routing_used,
      planner_model: router_model,
      fallback: %{
        used: not routing_used,
        reason: fallback_reason,
        policy: @fallback_policy
      }
    }
  end

  defp file_tags(path) do
    normalized = String.downcase(path) |> String.trim_leading("/")
    ext = Path.extname(normalized)
    name = Path.basename(normalized)
    segments = String.split(normalized, "/", trim: true)
    top_level = List.first(segments) || name
    {is_doc, is_test, is_code} = classify_file(path)

    config =
      top_level in ["config", ".github", ".circleci", ".buildkite"] or
        MapSet.member?(@config_extensions, ext) or
        MapSet.member?(@config_names, name)

    ci =
      top_level in [".github", ".circleci", ".buildkite"] or
        String.contains?(normalized, "/workflows/")

    cli =
      top_level in ["bin", "cmd"] or
        Enum.any?(segments, &(&1 in ["cli", "commands"]))

    security = Enum.any?(@security_hints, &String.contains?(normalized, &1))

    contract =
      Enum.any?(@contract_hints, &String.contains?(normalized, &1)) or
        String.starts_with?(normalized, "priv/openapi/")

    surface_bucket =
      cond do
        is_doc -> "docs"
        is_test -> "tests"
        ci -> "ci"
        config -> "config"
        contract -> "public_surface"
        true -> top_level
      end

    %{
      doc: is_doc,
      test: is_test,
      code: is_code,
      config: config,
      ci: ci,
      cli: cli,
      security: security,
      contract: contract,
      surface_bucket: surface_bucket
    }
  end

  defp repo_signal_text(repo_context) do
    repo_context.signals
    |> Enum.map(fn {key, value} -> "#{key}=#{value}" end)
    |> Enum.sort()
    |> Enum.join(", ")
    |> then(fn
      "" -> "none"
      value -> value
    end)
  end

  defp classification_text(diff_classification) do
    diff_classification
    |> Map.drop([:surface_buckets])
    |> Enum.map(fn {key, value} -> "#{key}=#{inspect(value)}" end)
    |> Enum.sort()
    |> Enum.join(", ")
  end

  # --- Helpers ---

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

  defp crash_fallback(diff_text, opts, state, reason) do
    summary = safe_parse_diff(diff_text)
    metadata = opts |> Keyword.get(:metadata, %{}) |> normalize_metadata()
    repo_context = inspect_repo_context(metadata)

    case safe_planner_inputs(state) do
      {:ok, personas, routing} ->
        required = required_reviewers(routing, summary.code_changed)
        diff_classification = classify_diff(summary, repo_context)
        size_bucket = classify_size(summary)
        model_tier = determine_model_tier(summary, diff_classification, repo_context)

        panel_size =
          determine_panel_size(routing, personas, required, diff_classification, repo_context)

        eligible =
          eligible_bench(
            personas,
            routing,
            required,
            panel_size,
            diff_classification,
            repo_context
          )

        panel =
          build_ranked_fallback_panel(
            personas,
            routing,
            required,
            eligible,
            panel_size,
            diff_classification,
            repo_context
          )

        all_reviewers = Enum.map(personas, & &1.id)

        %{
          panel: panel,
          reserves: Enum.reject(all_reviewers, &(&1 in panel)),
          model_tier: model_tier,
          size_bucket: size_bucket,
          routing_used: false,
          planner_trace:
            planner_trace(
              summary,
              diff_classification,
              repo_context,
              eligible,
              panel,
              model_tier,
              size_bucket,
              @default_router_model,
              required,
              false,
              reason
            )
        }

      :error ->
        static_crash_fallback(summary, repo_context, reason)
    end
  end

  defp static_crash_fallback(summary, repo_context, reason) do
    size_bucket = classify_size(summary)
    model_tier = classify_model_tier_safe(summary)
    panel = @default_crash_panel
    diff_classification = classify_diff(summary, repo_context)

    %{
      panel: panel,
      reserves: [],
      model_tier: model_tier,
      size_bucket: size_bucket,
      routing_used: false,
      planner_trace:
        planner_trace(
          summary,
          diff_classification,
          repo_context,
          panel,
          panel,
          model_tier,
          size_bucket,
          @default_router_model,
          ["trace"],
          false,
          reason
        )
    }
  end

  defp classify_model_tier_safe(summary) do
    classify_model_tier(summary)
  rescue
    _ -> :standard
  end

  defp safe_planner_inputs(%{config_server: config_server}) do
    try do
      {:ok, Cerberus.Config.personas(config_server), Cerberus.Config.routing(config_server)}
    rescue
      _ -> :error
    catch
      _, _ -> :error
    end
  end

  defp safe_parse_diff(text) when is_binary(text) do
    parse_diff(text)
  rescue
    _ -> empty_summary()
  end

  defp safe_parse_diff(_), do: empty_summary()

  defp non_empty_string(val, _default) when is_binary(val) and val != "", do: val
  defp non_empty_string(_, default), do: default

  defp normalize_metadata(metadata) when is_map(metadata), do: metadata
  defp normalize_metadata(metadata) when is_list(metadata), do: Map.new(metadata)
  defp normalize_metadata(_), do: %{}

  defp sanitize_prompt_value(val) when is_binary(val) do
    val
    |> String.replace(~r/[\n\r]/, " ")
    |> String.slice(0, 200)
  end

  defp sanitize_prompt_value(_), do: "unknown"
end
