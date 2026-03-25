defmodule Cerberus.Config.Loader do
  @moduledoc false

  alias Cerberus.Config.Diagnostic
  alias Cerberus.Config.Persona

  @supported_perspectives %{
    "correctness" => :correctness,
    "security" => :security,
    "testing" => :testing,
    "architecture" => :architecture,
    "resilience" => :resilience,
    "maintainability" => :maintainability
  }
  @supported_override_policies %{
    "pr_author" => :pr_author,
    "write_access" => :write_access,
    "maintainers_only" => :maintainers_only
  }
  @supported_model_tiers %{"flash" => :flash, "standard" => :standard, "pro" => :pro}
  @supported_model_pool_tiers %{"wave1" => :wave1, "wave2" => :wave2, "wave3" => :wave3}
  @supported_provider_adapters MapSet.new(["openrouter", "deterministic"])
  @tier_to_pool %{flash: :wave1, standard: :wave2, pro: :wave3}

  @required_model_pools ~w(wave1 wave2 wave3)
  @allowed_provider_keys MapSet.new(~w(adapter))
  @allowed_model_keys MapSet.new(~w(provider name))
  @allowed_asset_keys MapSet.new(~w(path content))
  @allowed_reviewer_keys MapSet.new(
                           ~w(id name perspective prompt template model description override tools)
                         )
  @allowed_routing_keys MapSet.new(
                          ~w(enabled model panel_size always_include fallback_panel include_if_code_changed)
                        )
  @allowed_verdict_keys MapSet.new(~w(fail_on warn_on confidence_min))
  @allowed_override_keys MapSet.new(
                           ~w(providers models model_pools prompts templates reviewers routing verdict)
                         )
  @provider_source_keys %{"adapter" => :adapter}
  @model_source_keys %{"provider" => :provider, "name" => :name}
  @reviewer_source_keys %{
    "perspective" => :perspective,
    "prompt" => :prompt,
    "template" => :template,
    "model" => :model,
    "description" => :description,
    "override" => :override,
    "tools" => :tools
  }
  @routing_source_keys %{
    "enabled" => :enabled,
    "model" => :model,
    "panel_size" => :panel_size,
    "always_include" => :always_include,
    "fallback_panel" => :fallback_panel,
    "include_if_code_changed" => :include_if_code_changed
  }
  @verdict_source_keys %{
    "fail_on" => :fail_on,
    "warn_on" => :warn_on,
    "confidence_min" => :confidence_min
  }

  @spec load(String.t(), map()) :: {:ok, map()} | {:error, {:invalid_config, [Diagnostic.t()]}}
  def load(repo_root, overrides \\ %{}) do
    override_map = stringify_keys(overrides)
    config_path = Path.join(repo_root, "defaults/config.yml")
    top_level_override_diagnostics = validate_override_keys(override_map)

    case YamlElixir.read_from_file(config_path) do
      {:ok, raw_defaults} ->
        {defaults_sections, default_diagnostics} = parse_defaults(raw_defaults)
        {override_sections, override_diagnostics} = parse_overrides(override_map)
        merged = merge_sections(defaults_sections, override_sections)
        {loaded_assets, asset_diagnostics, asset_mtimes} = load_assets(merged, repo_root)
        validation_diagnostics = validate_resolved(loaded_assets)

        diagnostics =
          top_level_override_diagnostics ++
            default_diagnostics ++
            override_diagnostics ++ asset_diagnostics ++ validation_diagnostics

        if diagnostics == [] do
          {:ok, build_state(loaded_assets, repo_root, config_path, asset_mtimes, override_map)}
        else
          {:error, {:invalid_config, Enum.sort_by(diagnostics, &{&1.source, &1.path})}}
        end

      {:error, reason} ->
        {:error,
         {:invalid_config, [diagnostic("default", "defaults/config.yml", inspect(reason))]}}
    end
  end

  @spec resolve_panel(map(), [String.t()], atom()) :: {:ok, [map()]} | {:error, term()}
  def resolve_panel(state, panel_ids, model_tier) when is_list(panel_ids) do
    tier = tier_to_string(model_tier)

    Enum.reduce_while(panel_ids, {:ok, []}, fn reviewer_id, {:ok, acc} ->
      case Map.fetch(state.persona_by_id, reviewer_id) do
        :error ->
          {:halt, {:error, {:unknown_reviewer, reviewer_id}}}

        {:ok, reviewer} ->
          case resolve_model(state, reviewer, tier) do
            {:ok, {model_id, model}} ->
              prompt_asset = Map.fetch!(state.prompts, reviewer.prompt_id)
              template_asset = Map.fetch!(state.templates, reviewer.template_id)

              entry = %{
                reviewer_id: reviewer.id,
                reviewer: reviewer,
                perspective: Atom.to_string(reviewer.perspective),
                model_id: model_id,
                model_name: model.name,
                provider_id: model.provider_id,
                prompt_id: reviewer.prompt_id,
                prompt_path: reviewer.prompt_path,
                prompt_digest: reviewer.prompt_digest,
                template_id: reviewer.template_id,
                template_path: reviewer.template_path,
                template_digest: reviewer.template_digest,
                prompt: reviewer.prompt,
                template: reviewer.template,
                sources: %{
                  perspective: source_label(reviewer.sources[:perspective] || "default"),
                  prompt:
                    effective_source([
                      reviewer.sources[:prompt],
                      prompt_asset.sources[:path],
                      prompt_asset.sources[:content]
                    ]),
                  template:
                    effective_source([
                      reviewer.sources[:template],
                      template_asset.sources[:path],
                      template_asset.sources[:content]
                    ]),
                  model:
                    effective_source([
                      reviewer.sources[:model],
                      state.model_pool_sources[tier],
                      model.sources[:provider],
                      model.sources[:name]
                    ]),
                  provider: effective_source([model.sources[:provider]])
                }
              }

              {:cont, {:ok, acc ++ [entry]}}

            {:error, reason} ->
              {:halt, {:error, reason}}
          end
      end
    end)
  end

  @spec resolved_snapshot(map(), keyword()) :: map()
  def resolved_snapshot(state, opts \\ []) do
    panel_ids =
      Keyword.get(opts, :panel, state.reviewer_order)
      |> Enum.map(&to_string/1)

    model_tier = Keyword.get(opts, :model_tier, :standard)
    {:ok, resolved_panel} = resolve_panel(state, panel_ids, model_tier)

    planner_model = Map.fetch!(state.models, state.routing.model_id)

    %{
      model_tier: tier_to_string(model_tier),
      planner_model: %{
        id: state.routing.model_id,
        provider: %{
          value: planner_model.provider_id,
          source:
            effective_source([state.routing_sources[:model], planner_model.sources[:provider]])
        },
        model: %{
          value: planner_model.name,
          source: effective_source([state.routing_sources[:model], planner_model.sources[:name]])
        }
      },
      reviewers:
        Enum.map(resolved_panel, fn entry ->
          reviewer = entry.reviewer

          %{
            id: reviewer.id,
            perspective: %{
              value: Atom.to_string(reviewer.perspective),
              source: entry.sources.perspective
            },
            provider: %{value: entry.provider_id, source: entry.sources.provider},
            model: %{
              id: entry.model_id,
              value: entry.model_name,
              source: entry.sources.model
            },
            prompt: %{
              id: entry.prompt_id,
              path: entry.prompt_path,
              digest: entry.prompt_digest,
              source: entry.sources.prompt
            },
            template: %{
              id: entry.template_id,
              path: entry.template_path,
              digest: entry.template_digest,
              source: entry.sources.template
            }
          }
        end)
    }
  end

  defp parse_defaults(raw) when is_map(raw) do
    {
      %{
        providers: parse_providers(Map.get(raw, "providers"), "default"),
        models: parse_models(Map.get(raw, "models"), "default"),
        model_pools: parse_model_pools(Map.get(raw, "model_pools"), "default"),
        prompts: parse_assets(Map.get(raw, "prompts"), "prompts", "default"),
        templates: parse_assets(Map.get(raw, "templates"), "templates", "default"),
        reviewers: parse_reviewers(Map.get(raw, "reviewers"), "default"),
        routing: parse_routing(Map.get(raw, "routing"), "default"),
        verdict: parse_verdict(Map.get(raw, "verdict"), "default")
      },
      []
    }
    |> collect_parse_errors()
  end

  defp parse_defaults(raw) do
    {nil, [diagnostic("default", "defaults/config.yml", "expected map", raw)]}
  end

  defp parse_overrides(%{} = raw) do
    {
      %{
        providers: parse_providers(Map.get(raw, "providers", %{}), "override"),
        models: parse_models(Map.get(raw, "models", %{}), "override"),
        model_pools: parse_model_pools(Map.get(raw, "model_pools", %{}), "override"),
        prompts: parse_assets(Map.get(raw, "prompts", %{}), "prompts", "override"),
        templates: parse_assets(Map.get(raw, "templates", %{}), "templates", "override"),
        reviewers: parse_reviewers(Map.get(raw, "reviewers", %{}), "override"),
        routing: parse_routing(Map.get(raw, "routing", %{}), "override"),
        verdict: parse_verdict(Map.get(raw, "verdict", %{}), "override")
      },
      []
    }
    |> collect_parse_errors()
  end

  defp collect_parse_errors({sections, diagnostics}) do
    extra =
      sections
      |> Enum.flat_map(fn
        {_key, {:ok, _value}} -> []
        {_key, {:error, errors}} -> errors
      end)

    parsed =
      Map.new(sections, fn
        {key, {:ok, value}} -> {key, value}
        {key, {:error, _errors}} -> {key, default_section_value(key)}
      end)

    {parsed, diagnostics ++ extra}
  end

  defp default_section_value(:providers), do: %{}
  defp default_section_value(:models), do: %{}
  defp default_section_value(:model_pools), do: %{values: %{}, sources: %{}}
  defp default_section_value(:prompts), do: %{}
  defp default_section_value(:templates), do: %{}
  defp default_section_value(:reviewers), do: %{entries: %{}, order: []}
  defp default_section_value(:routing), do: %{data: %{}, sources: %{}}
  defp default_section_value(:verdict), do: %{data: %{}, sources: %{}}

  defp parse_providers(nil, source) do
    {:error, [diagnostic(source, "providers", "is required")]}
  end

  defp parse_providers(raw, source) when is_map(raw) do
    diagnostics = validate_nested_keys(raw, @allowed_provider_keys, source, "providers")

    providers =
      Enum.map(raw, fn {id, attrs} ->
        path = "providers.#{id}"

        case attrs do
          %{} ->
            {id,
             %{}
             |> Map.put(:id, id)
             |> maybe_put_attr(:adapter, attrs, "adapter")
             |> Map.put(:sources, attr_sources(attrs, source, @provider_source_keys))}

          value ->
            {:diagnostic, diagnostic(source, path, "expected map", value)}
        end
      end)

    diagnostics = diagnostics ++ collect_inline_diagnostics(providers)

    {:ok, Map.new(Enum.reject(providers, &match?({:diagnostic, _}, &1)))}
    |> with_diagnostics(diagnostics)
  end

  defp parse_providers(raw, source) do
    {:error, [diagnostic(source, "providers", "expected map", raw)]}
  end

  defp parse_models(nil, source) do
    {:error, [diagnostic(source, "models", "is required")]}
  end

  defp parse_models(raw, source) when is_map(raw) do
    diagnostics = validate_nested_keys(raw, @allowed_model_keys, source, "models")

    models =
      Enum.map(raw, fn {id, attrs} ->
        path = "models.#{id}"

        case attrs do
          %{} ->
            {id,
             %{}
             |> Map.put(:id, id)
             |> maybe_put_attr(:provider_id, attrs, "provider")
             |> maybe_put_attr(:name, attrs, "name")
             |> Map.put(:sources, attr_sources(attrs, source, @model_source_keys))}

          value ->
            {:diagnostic, diagnostic(source, path, "expected map", value)}
        end
      end)

    diagnostics = diagnostics ++ collect_inline_diagnostics(models)

    {:ok, Map.new(Enum.reject(models, &match?({:diagnostic, _}, &1)))}
    |> with_diagnostics(diagnostics)
  end

  defp parse_models(raw, source) do
    {:error, [diagnostic(source, "models", "expected map", raw)]}
  end

  defp parse_model_pools(nil, source) do
    {:error, [diagnostic(source, "model_pools", "is required")]}
  end

  defp parse_model_pools(raw, source) when is_map(raw) do
    diagnostics =
      Enum.flat_map(raw, fn {tier, models} ->
        path = "model_pools.#{tier}"

        unsupported_tier =
          if supported_model_pool_tier?(tier),
            do: [],
            else: [diagnostic(source, path, "unsupported model pool tier", tier)]

        cond do
          not is_list(models) ->
            unsupported_tier ++ [diagnostic(source, path, "expected list", models)]

          Enum.all?(models, &is_binary/1) ->
            unsupported_tier

          true ->
            unsupported_tier ++ [diagnostic(source, path, "expected list of strings", models)]
        end
      end)

    {:ok, %{values: raw, sources: Map.new(Map.keys(raw), &{&1, source})}}
    |> with_diagnostics(diagnostics)
  end

  defp parse_model_pools(raw, source) do
    {:error, [diagnostic(source, "model_pools", "expected map", raw)]}
  end

  defp parse_assets(nil, section, source) do
    {:error, [diagnostic(source, section, "is required")]}
  end

  defp parse_assets(raw, section, source) when is_map(raw) do
    diagnostics = validate_nested_keys(raw, @allowed_asset_keys, source, section)

    entries =
      Enum.map(raw, fn {id, attrs} ->
        path = "#{section}.#{id}"

        case attrs do
          %{} ->
            {id,
             %{}
             |> Map.put(:id, id)
             |> maybe_put_attr(:path, attrs, "path")
             |> maybe_put_attr(:content, attrs, "content")
             |> Map.put(:sources, asset_sources(attrs, source))}

          value ->
            {:diagnostic, diagnostic(source, path, "expected map", value)}
        end
      end)

    diagnostics = diagnostics ++ collect_inline_diagnostics(entries)

    {:ok, Map.new(Enum.reject(entries, &match?({:diagnostic, _}, &1)))}
    |> with_diagnostics(diagnostics)
  end

  defp parse_assets(raw, section, source) do
    {:error, [diagnostic(source, section, "expected map", raw)]}
  end

  defp parse_reviewers(nil, source) do
    {:error, [diagnostic(source, "reviewers", "is required")]}
  end

  defp parse_reviewers(raw, source) when is_map(raw) do
    diagnostics = validate_nested_keys(raw, @allowed_reviewer_keys, source, "reviewers")

    reviewers =
      Enum.map(raw, fn {id, attrs} ->
        path = "reviewers.#{id}"

        case attrs do
          %{} ->
            if attrs["id"] not in [nil, id] do
              {:diagnostic,
               diagnostic(source, "#{path}.id", "must match reviewer key", attrs["id"])}
            else
              {id, reviewer_entry(id, attrs, source)}
            end

          value ->
            {:diagnostic, diagnostic(source, path, "expected map", value)}
        end
      end)

    diagnostics = diagnostics ++ collect_inline_diagnostics(reviewers)

    {:ok,
     %{
       entries: Map.new(Enum.reject(reviewers, &match?({:diagnostic, _}, &1))),
       order:
         reviewers
         |> Enum.reject(&match?({:diagnostic, _}, &1))
         |> Enum.map(fn {id, _entry} -> id end)
     }}
    |> with_diagnostics(diagnostics)
  end

  defp parse_reviewers(raw, source) when is_list(raw) do
    {entries, diagnostics, order, seen} =
      Enum.with_index(raw)
      |> Enum.reduce({%{}, [], [], MapSet.new()}, fn {item, index},
                                                     {entries, diagnostics, order, seen} ->
        path = "reviewers[#{index}]"

        case item do
          %{} ->
            id = item["id"] || item["name"]

            cond do
              not is_binary(id) or id == "" ->
                {entries,
                 diagnostics ++ [diagnostic(source, "#{path}.id", "is required", item["id"])],
                 order, seen}

              MapSet.member?(seen, id) ->
                {entries, diagnostics ++ [diagnostic(source, path, "duplicate reviewer id", id)],
                 order, seen}

              true ->
                {Map.put(entries, id, reviewer_entry(id, item, source)), diagnostics,
                 order ++ [id], MapSet.put(seen, id)}
            end

          value ->
            {entries, diagnostics ++ [diagnostic(source, path, "expected map", value)], order,
             seen}
        end
      end)

    _ = seen
    {:ok, %{entries: entries, order: order}} |> with_diagnostics(diagnostics)
  end

  defp parse_reviewers(raw, source) do
    {:error, [diagnostic(source, "reviewers", "expected map or list", raw)]}
  end

  defp parse_routing(nil, source) do
    {:error, [diagnostic(source, "routing", "is required")]}
  end

  defp parse_routing(raw, source) when is_map(raw) do
    diagnostics = validate_keys(raw, @allowed_routing_keys, source, "routing")

    diagnostics =
      diagnostics ++
        wrong_type_diagnostic(
          raw["enabled"],
          &is_boolean/1,
          source,
          "routing.enabled",
          "expected boolean"
        ) ++
        wrong_type_diagnostic(
          raw["model"],
          &is_binary/1,
          source,
          "routing.model",
          "expected string"
        ) ++
        wrong_type_diagnostic(
          raw["panel_size"],
          &is_integer/1,
          source,
          "routing.panel_size",
          "expected integer"
        ) ++
        list_of_strings_diagnostic(raw["always_include"], source, "routing.always_include") ++
        list_of_strings_diagnostic(raw["fallback_panel"], source, "routing.fallback_panel") ++
        list_of_strings_diagnostic(
          raw["include_if_code_changed"],
          source,
          "routing.include_if_code_changed"
        )

    {:ok,
     %{
       data:
         %{}
         |> maybe_put_attr(:enabled, raw, "enabled")
         |> maybe_put_attr(:model, raw, "model")
         |> maybe_put_attr(:panel_size, raw, "panel_size")
         |> maybe_put_attr(:always_include, raw, "always_include")
         |> maybe_put_attr(:fallback_panel, raw, "fallback_panel")
         |> maybe_put_attr(:include_if_code_changed, raw, "include_if_code_changed"),
       sources: attr_sources(raw, source, @routing_source_keys)
     }}
    |> with_diagnostics(diagnostics)
  end

  defp parse_routing(raw, source) do
    {:error, [diagnostic(source, "routing", "expected map", raw)]}
  end

  defp parse_verdict(nil, _source) do
    {:ok, %{data: %{}, sources: %{}}}
  end

  defp parse_verdict(raw, source) when is_map(raw) do
    diagnostics = validate_keys(raw, @allowed_verdict_keys, source, "verdict")

    diagnostics =
      diagnostics ++
        wrong_type_diagnostic(
          raw["fail_on"],
          &is_binary/1,
          source,
          "verdict.fail_on",
          "expected string"
        ) ++
        wrong_type_diagnostic(
          raw["warn_on"],
          &is_binary/1,
          source,
          "verdict.warn_on",
          "expected string"
        ) ++
        wrong_type_diagnostic(
          raw["confidence_min"],
          &(is_float(&1) or is_integer(&1)),
          source,
          "verdict.confidence_min",
          "expected number"
        )

    {:ok,
     %{
       data:
         %{}
         |> maybe_put_attr(:fail_on, raw, "fail_on")
         |> maybe_put_attr(:warn_on, raw, "warn_on")
         |> maybe_put_attr(:confidence_min, raw, "confidence_min"),
       sources: attr_sources(raw, source, @verdict_source_keys)
     }}
    |> with_diagnostics(diagnostics)
  end

  defp parse_verdict(raw, source) do
    {:error, [diagnostic(source, "verdict", "expected map", raw)]}
  end

  defp reviewer_entry(id, attrs, source) do
    %{}
    |> Map.put(:id, id)
    |> Map.put(:name, attrs["name"] || id)
    |> maybe_put_attr(:perspective, attrs, "perspective")
    |> maybe_put_attr(:prompt_id, attrs, "prompt")
    |> maybe_put_attr(:template_id, attrs, "template")
    |> maybe_put_attr(:model_policy, attrs, "model")
    |> maybe_put_attr(:description, attrs, "description")
    |> maybe_put_attr(:override, attrs, "override")
    |> maybe_put_attr(:tools, attrs, "tools")
    |> Map.put(:sources, attr_sources(attrs, source, @reviewer_source_keys))
  end

  defp merge_sections(defaults, overrides) do
    %{
      providers: merge_entries(defaults.providers, overrides.providers),
      models: merge_entries(defaults.models, overrides.models),
      model_pools: merge_pool_data(defaults.model_pools, overrides.model_pools),
      prompts: merge_entries(defaults.prompts, overrides.prompts),
      templates: merge_entries(defaults.templates, overrides.templates),
      reviewers: merge_reviewers(defaults.reviewers, overrides.reviewers),
      routing: merge_data(defaults.routing, overrides.routing),
      verdict: merge_data(defaults.verdict, overrides.verdict)
    }
  end

  defp merge_entries(defaults, overrides) do
    Map.merge(defaults, overrides, fn _id, default_entry, override_entry ->
      default_entry
      |> Map.merge(override_entry)
      |> Map.put(
        :sources,
        Map.merge(Map.get(default_entry, :sources, %{}), Map.get(override_entry, :sources, %{}))
      )
    end)
  end

  defp merge_data(%{data: default_data, sources: default_sources}, %{
         data: override_data,
         sources: override_sources
       }) do
    %{
      data: Map.merge(default_data, override_data, fn _key, _old, new -> new end),
      sources: Map.merge(default_sources, override_sources)
    }
  end

  defp merge_pool_data(%{values: default_values, sources: default_sources}, %{
         values: override_values,
         sources: override_sources
       }) do
    %{
      values: Map.merge(default_values, override_values, fn _key, _old, new -> new end),
      sources: Map.merge(default_sources, override_sources)
    }
  end

  defp merge_reviewers(defaults, overrides) do
    default_entries = defaults.entries
    override_entries = overrides.entries

    entries =
      Map.merge(default_entries, override_entries, fn _id, default_entry, override_entry ->
        default_tools = normalize_tools(Map.get(default_entry, :tools))
        override_tools = normalize_tools(Map.get(override_entry, :tools))

        merged =
          default_entry
          |> Map.merge(override_entry)
          |> Map.put(:sources, Map.merge(default_entry.sources, override_entry.sources))
          |> Map.put(:tools, Map.merge(default_tools, override_tools))

        if Map.get(override_entry, :tools) == nil,
          do: Map.put(merged, :tools, default_tools),
          else: merged
      end)

    added_ids =
      override_entries
      |> Map.keys()
      |> Enum.reject(&Map.has_key?(default_entries, &1))
      |> Enum.sort()

    %{entries: entries, order: defaults.order ++ added_ids}
  end

  defp load_assets(merged, repo_root) do
    with {prompts, [], prompt_mtimes} <- load_asset_entries(merged.prompts, repo_root, "prompts"),
         {templates, [], template_mtimes} <-
           load_asset_entries(merged.templates, repo_root, "templates") do
      {Map.put(merged, :prompts, prompts) |> Map.put(:templates, templates), [],
       Map.merge(prompt_mtimes, template_mtimes)}
    else
      {_entries, diagnostics, _mtimes} ->
        {merged, diagnostics, %{}}
    end
  end

  defp load_asset_entries(entries, repo_root, section) do
    Enum.reduce(entries, {%{}, [], %{}}, fn {id, entry}, {acc, diagnostics, mtimes} ->
      path = "#{section}.#{id}"
      content = Map.get(entry, :content)
      file_path = Map.get(entry, :path)

      cond do
        is_binary(content) ->
          if String.trim(content) == "" do
            {acc,
             diagnostics ++
               [diagnostic(source_from_entry(entry), path, "asset content cannot be empty")],
             mtimes}
          else
            loaded = load_inline_asset(Map.put(entry, :content, content), repo_root)
            {Map.put(acc, id, loaded), diagnostics, mtimes}
          end

        is_binary(file_path) ->
          absolute_path = resolve_path(file_path, repo_root)

          case File.read(absolute_path) do
            {:ok, content} ->
              if String.trim(content) == "" do
                {acc,
                 diagnostics ++
                   [
                     diagnostic(
                       source_from_entry(entry),
                       path,
                       "asset file cannot be empty",
                       display_path(absolute_path, repo_root)
                     )
                   ], mtimes}
              else
                loaded =
                  entry
                  |> Map.put(:path, display_path(absolute_path, repo_root))
                  |> Map.put(:content, content)
                  |> Map.put(:digest, digest(content))

                mtime =
                  case File.stat(absolute_path) do
                    {:ok, stat} -> %{absolute_path => stat.mtime}
                    _ -> %{}
                  end

                {Map.put(acc, id, loaded), diagnostics, Map.merge(mtimes, mtime)}
              end

            {:error, _reason} ->
              {acc,
               diagnostics ++
                 [
                   diagnostic(
                     source_from_entry(entry),
                     path,
                     "asset file not found",
                     display_path(absolute_path, repo_root)
                   )
                 ], mtimes}
          end

        true ->
          {acc,
           diagnostics ++
             [diagnostic(source_from_entry(entry), path, "must define path or content")], mtimes}
      end
    end)
  end

  defp validate_resolved(merged) do
    providers = merged.providers
    models = merged.models
    model_pools = merged.model_pools.values
    reviewers = merged.reviewers.entries
    routing = merged.routing.data

    diagnostics =
      validate_providers(providers) ++
        validate_models(models, providers) ++
        validate_model_pools(model_pools, merged.model_pools.sources, models, reviewers) ++
        validate_reviewers(reviewers, merged.prompts, merged.templates, models) ++
        validate_routing(routing, merged.routing.sources, reviewers, models) ++
        validate_verdict(merged.verdict.data, merged.verdict.sources)

    diagnostics
  end

  defp validate_providers(providers) do
    if map_size(providers) == 0 do
      [diagnostic("default", "providers", "must not be empty")]
    else
      Enum.flat_map(providers, fn {id, provider} ->
        cond do
          not is_binary(provider.adapter) or provider.adapter == "" ->
            [
              diagnostic(
                source_from_entry(provider),
                "providers.#{id}.adapter",
                "is required",
                provider.adapter
              )
            ]

          MapSet.member?(@supported_provider_adapters, provider.adapter) ->
            []

          true ->
            [
              diagnostic(
                source_from_entry(provider),
                "providers.#{id}.adapter",
                "unsupported adapter",
                provider.adapter
              )
            ]
        end
      end)
    end
  end

  defp validate_models(models, providers) do
    if map_size(models) == 0 do
      [diagnostic("default", "models", "must not be empty")]
    else
      Enum.flat_map(models, fn {id, model} ->
        provider = Map.get(providers, model.provider_id)
        source = source_from_entry(model)

        cond do
          not is_binary(model.provider_id) or model.provider_id == "" ->
            [diagnostic(source, "models.#{id}.provider", "is required", model.provider_id)]

          provider == nil ->
            [
              diagnostic(
                source,
                "models.#{id}.provider",
                "references unknown provider",
                model.provider_id
              )
            ]

          not is_binary(model.name) or model.name == "" ->
            [diagnostic(source, "models.#{id}.name", "is required", model.name)]

          not provider_supports_model?(provider.adapter, model.name) ->
            [
              diagnostic(source, "models.#{id}", "invalid provider/model combination", %{
                provider: model.provider_id,
                model: model.name
              })
            ]

          true ->
            []
        end
      end)
    end
  end

  defp validate_model_pools(model_pools, pool_sources, models, reviewers) do
    required =
      if Enum.any?(reviewers, fn {_id, reviewer} -> reviewer.model_policy == "pool" end) do
        @required_model_pools
      else
        []
      end

    missing_required =
      Enum.flat_map(required, fn tier ->
        if Map.get(model_pools, tier, []) == [] do
          [
            diagnostic(
              Map.get(pool_sources, tier, "default"),
              "model_pools.#{tier}",
              "must not be empty"
            )
          ]
        else
          []
        end
      end)

    refs =
      Enum.flat_map(model_pools, fn {tier, ids} ->
        Enum.flat_map(ids, fn id ->
          if Map.has_key?(models, id) do
            []
          else
            [
              diagnostic(
                Map.get(pool_sources, tier, "default"),
                "model_pools.#{tier}",
                "references unknown model",
                id
              )
            ]
          end
        end)
      end)

    missing_required ++ refs
  end

  defp validate_reviewers(reviewers, prompts, templates, models) do
    if map_size(reviewers) == 0 do
      [diagnostic("default", "reviewers", "must not be empty")]
    else
      Enum.flat_map(reviewers, fn {id, reviewer} ->
        source = source_from_entry(reviewer)

        []
        |> require_string(source, "reviewers.#{id}.perspective", reviewer.perspective)
        |> validate_reviewer_perspective(source, id, reviewer.perspective)
        |> require_string(source, "reviewers.#{id}.prompt", reviewer.prompt_id)
        |> require_string(source, "reviewers.#{id}.template", reviewer.template_id)
        |> require_string(source, "reviewers.#{id}.model", reviewer.model_policy)
        |> validate_reviewer_override(source, id, reviewer.override)
        |> maybe_require_known(source, "reviewers.#{id}.prompt", reviewer.prompt_id, prompts)
        |> maybe_require_known(
          source,
          "reviewers.#{id}.template",
          reviewer.template_id,
          templates
        )
        |> validate_reviewer_model(source, id, reviewer.model_policy, models)
        |> maybe_tools_map(source, "reviewers.#{id}.tools", reviewer.tools)
      end)
    end
  end

  defp validate_routing(routing, sources, reviewers, models) do
    reviewer_ids = Map.keys(reviewers) |> MapSet.new()
    source = Map.get(sources, :panel_size, "default")

    []
    |> require_positive_integer(source, "routing.panel_size", routing.panel_size)
    |> require_string(Map.get(sources, :model, "default"), "routing.model", routing.model)
    |> maybe_require_known(
      Map.get(sources, :model, "default"),
      "routing.model",
      routing.model,
      models
    )
    |> validate_reviewer_refs(
      Map.get(sources, :always_include, "default"),
      "routing.always_include",
      routing.always_include || [],
      reviewer_ids
    )
    |> validate_reviewer_refs(
      Map.get(sources, :fallback_panel, "default"),
      "routing.fallback_panel",
      routing.fallback_panel || [],
      reviewer_ids
    )
    |> validate_reviewer_refs(
      Map.get(sources, :include_if_code_changed, "default"),
      "routing.include_if_code_changed",
      routing.include_if_code_changed || [],
      reviewer_ids
    )
  end

  defp validate_verdict(verdict, sources) do
    confidence = verdict[:confidence_min]
    source = Map.get(sources, :confidence_min, "default")

    if confidence != nil and not (is_float(confidence) or is_integer(confidence)) do
      [diagnostic(source, "verdict.confidence_min", "expected number", confidence)]
    else
      []
    end
  end

  defp build_state(merged, repo_root, config_path, asset_mtimes, overrides) do
    prompts = merged.prompts
    templates = merged.templates

    personas =
      Enum.map(merged.reviewers.order, fn id ->
        reviewer = Map.fetch!(merged.reviewers.entries, id)
        prompt = Map.fetch!(prompts, reviewer.prompt_id)
        template = Map.fetch!(templates, reviewer.template_id)

        %Persona{
          id: id,
          name: reviewer.name || id,
          perspective: perspective_to_atom!(reviewer.perspective),
          prompt: prompt.content,
          prompt_id: reviewer.prompt_id,
          prompt_path: prompt.path,
          prompt_digest: prompt.digest,
          template: template.content,
          template_id: reviewer.template_id,
          template_path: template.path,
          template_digest: template.digest,
          model_policy: normalize_model_policy(reviewer.model_policy),
          model_id: normalize_fixed_model(reviewer.model_policy),
          provider_id: nil,
          description: reviewer.description,
          override: normalize_override_policy(reviewer.override),
          tools: normalize_tools(reviewer.tools),
          sources: reviewer.sources
        }
      end)

    persona_by_id = Map.new(personas, &{&1.id, &1})
    routing_model = Map.fetch!(merged.models, merged.routing.data.model)
    config_mtimes = file_mtimes([config_path])

    %{
      repo_root: repo_root,
      overrides: overrides,
      personas: personas,
      persona_by_id: persona_by_id,
      reviewer_order: merged.reviewers.order,
      prompts: prompts,
      templates: templates,
      providers: merged.providers,
      models: merged.models,
      model_pools:
        Map.new(merged.model_pools.values, fn {tier, ids} -> {tier_to_atom(tier), ids} end),
      model_pool_sources: merged.model_pools.sources,
      verdict_rules: resolved_verdict(merged.verdict.data),
      routing: %{
        panel_size: merged.routing.data.panel_size,
        always_include: merged.routing.data.always_include || [],
        fallback_panel: merged.routing.data.fallback_panel || [],
        include_if_code_changed: merged.routing.data.include_if_code_changed || [],
        enabled: merged.routing.data.enabled != false,
        model: routing_model.name,
        model_id: merged.routing.data.model,
        provider_id: routing_model.provider_id
      },
      routing_sources: merged.routing.sources,
      asset_mtimes: Map.merge(asset_mtimes, config_mtimes)
    }
  end

  defp resolved_verdict(data) do
    %{
      fail_on: data[:fail_on] || "any_critical_or_2_major",
      warn_on: data[:warn_on] || "any_major_or_5_minor_or_3_minor_same_category",
      confidence_min: data[:confidence_min] || 0.7
    }
  end

  defp resolve_model(state, reviewer, tier) do
    pool_tier = pool_tier_for(tier)

    case reviewer.model_policy do
      :pool ->
        case Map.get(state.model_pools, pool_tier, []) do
          [model_id | _] -> {:ok, {model_id, Map.fetch!(state.models, model_id)}}
          [] -> {:error, {:empty_model_pool, to_string(pool_tier)}}
        end

      model_id when is_binary(model_id) ->
        {:ok, {model_id, Map.fetch!(state.models, model_id)}}
    end
  end

  defp validate_override_keys(raw) when map_size(raw) == 0, do: []

  defp validate_override_keys(raw) do
    validate_keys(raw, @allowed_override_keys, "override", "overrides")
  end

  defp validate_keys(map, allowed, source, prefix) do
    Enum.flat_map(map, fn {key, value} ->
      if MapSet.member?(allowed, key) do
        []
      else
        [diagnostic(source, "#{prefix}.#{key}", "unsupported override key", value)]
      end
    end)
  end

  defp validate_nested_keys(entries, allowed, source, prefix) do
    Enum.flat_map(entries, fn {id, attrs} ->
      if is_map(attrs) do
        Enum.flat_map(attrs, fn {key, value} ->
          if MapSet.member?(allowed, key) do
            []
          else
            [diagnostic(source, "#{prefix}.#{id}.#{key}", "unsupported override key", value)]
          end
        end)
      else
        []
      end
    end)
  end

  defp wrong_type_diagnostic(nil, _predicate, _source, _path, _reason), do: []

  defp wrong_type_diagnostic(value, predicate, source, path, reason) do
    if predicate.(value), do: [], else: [diagnostic(source, path, reason, value)]
  end

  defp list_of_strings_diagnostic(nil, _source, _path), do: []

  defp list_of_strings_diagnostic(value, source, path) do
    cond do
      not is_list(value) ->
        [diagnostic(source, path, "expected list", value)]

      Enum.all?(value, &is_binary/1) ->
        []

      true ->
        [diagnostic(source, path, "expected list of strings", value)]
    end
  end

  defp require_string(diagnostics, _source, _path, value) when is_binary(value) and value != "",
    do: diagnostics

  defp require_string(diagnostics, source, path, value) do
    diagnostics ++ [diagnostic(source, path, "is required", value)]
  end

  defp require_positive_integer(diagnostics, _source, _path, value)
       when is_integer(value) and value > 0,
       do: diagnostics

  defp require_positive_integer(diagnostics, source, path, value) do
    diagnostics ++ [diagnostic(source, path, "must be a positive integer", value)]
  end

  defp maybe_require_known(diagnostics, _source, _path, nil, _entries), do: diagnostics

  defp maybe_require_known(diagnostics, source, path, id, entries) do
    if Map.has_key?(entries, id) do
      diagnostics
    else
      diagnostics ++ [diagnostic(source, path, "references unknown value", id)]
    end
  end

  defp validate_reviewer_model(diagnostics, _source, _id, "pool", _models), do: diagnostics

  defp validate_reviewer_model(diagnostics, source, id, model_id, models)
       when is_binary(model_id) do
    if Map.has_key?(models, model_id) do
      diagnostics
    else
      diagnostics ++
        [diagnostic(source, "reviewers.#{id}.model", "references unknown model", model_id)]
    end
  end

  defp validate_reviewer_model(diagnostics, source, id, value, _models) do
    diagnostics ++ [diagnostic(source, "reviewers.#{id}.model", "expected string", value)]
  end

  defp validate_reviewer_perspective(diagnostics, _source, _id, nil), do: diagnostics
  defp validate_reviewer_perspective(diagnostics, _source, _id, ""), do: diagnostics

  defp validate_reviewer_perspective(diagnostics, source, id, value) when is_binary(value) do
    if Map.has_key?(@supported_perspectives, value) do
      diagnostics
    else
      diagnostics ++
        [diagnostic(source, "reviewers.#{id}.perspective", "unsupported perspective", value)]
    end
  end

  defp validate_reviewer_perspective(diagnostics, source, id, value) do
    diagnostics ++ [diagnostic(source, "reviewers.#{id}.perspective", "expected string", value)]
  end

  defp validate_reviewer_override(diagnostics, _source, _id, nil), do: diagnostics
  defp validate_reviewer_override(diagnostics, _source, _id, ""), do: diagnostics

  defp validate_reviewer_override(diagnostics, source, id, value) when is_binary(value) do
    if Map.has_key?(@supported_override_policies, value) do
      diagnostics
    else
      diagnostics ++
        [diagnostic(source, "reviewers.#{id}.override", "unsupported override policy", value)]
    end
  end

  defp validate_reviewer_override(diagnostics, source, id, value) do
    diagnostics ++ [diagnostic(source, "reviewers.#{id}.override", "expected string", value)]
  end

  defp maybe_tools_map(diagnostics, _source, _path, nil), do: diagnostics
  defp maybe_tools_map(diagnostics, _source, _path, value) when is_map(value), do: diagnostics

  defp maybe_tools_map(diagnostics, source, path, value) do
    diagnostics ++ [diagnostic(source, path, "expected map", value)]
  end

  defp validate_reviewer_refs(diagnostics, _source, _path, [], _reviewer_ids), do: diagnostics

  defp validate_reviewer_refs(diagnostics, source, path, ids, reviewer_ids) do
    missing =
      Enum.flat_map(ids, fn id ->
        if MapSet.member?(reviewer_ids, id) do
          []
        else
          [diagnostic(source, path, "references unknown reviewer", id)]
        end
      end)

    diagnostics ++ missing
  end

  defp collect_inline_diagnostics(entries) do
    entries
    |> Enum.filter(&match?({:diagnostic, _}, &1))
    |> Enum.map(fn {:diagnostic, diagnostic} -> diagnostic end)
  end

  defp with_diagnostics({:ok, value}, []), do: {:ok, value}
  defp with_diagnostics({:ok, _value}, diagnostics), do: {:error, diagnostics}

  defp normalize_model_policy("pool"), do: :pool
  defp normalize_model_policy(value), do: value
  defp normalize_fixed_model("pool"), do: nil
  defp normalize_fixed_model(value), do: value

  defp perspective_to_atom!(value) when is_atom(value), do: value

  defp perspective_to_atom!(value) when is_binary(value),
    do: Map.fetch!(@supported_perspectives, value)

  defp normalize_override_policy(nil), do: nil
  defp normalize_override_policy(value) when is_atom(value), do: value

  defp normalize_override_policy(value) when is_binary(value) do
    Map.fetch!(@supported_override_policies, value)
  end

  defp normalize_tools(nil), do: %{}
  defp normalize_tools(value) when is_map(value), do: value
  defp normalize_tools(_value), do: %{}

  defp resolve_path(path, repo_root) do
    if Path.type(path) == :absolute, do: path, else: Path.join(repo_root, path)
  end

  defp display_path(path, repo_root) do
    expanded_repo = Path.expand(repo_root)
    expanded_path = Path.expand(path)

    if String.starts_with?(expanded_path, expanded_repo <> "/") do
      Path.relative_to(expanded_path, expanded_repo)
    else
      expanded_path
    end
  end

  defp file_mtimes(paths) do
    Enum.reduce(paths, %{}, fn path, acc ->
      case File.stat(path) do
        {:ok, stat} -> Map.put(acc, path, stat.mtime)
        _ -> acc
      end
    end)
  end

  defp load_inline_asset(entry, repo_root) do
    path = Map.get(entry, :path)

    display_path_value =
      if is_binary(path), do: display_path(resolve_path(path, repo_root), repo_root), else: nil

    entry
    |> Map.put(:path, display_path_value)
    |> Map.put(:digest, digest(Map.fetch!(entry, :content)))
  end

  defp digest(content) do
    "sha256:" <> Base.encode16(:crypto.hash(:sha256, content), case: :lower)
  end

  defp provider_supports_model?(adapter, model_name) do
    case adapter do
      "openrouter" -> String.starts_with?(model_name, "openrouter/")
      "deterministic" -> String.starts_with?(model_name, "deterministic/")
      _ -> false
    end
  end

  defp tier_to_atom(value) when is_atom(value), do: value

  defp tier_to_atom(value) when is_binary(value),
    do: Map.fetch!(@supported_model_pool_tiers, value)

  defp tier_to_string(value) when is_binary(value), do: value
  defp tier_to_string(value) when is_atom(value), do: Atom.to_string(value)

  defp pool_tier_for(value) when is_binary(value) do
    cond do
      Map.has_key?(@supported_model_tiers, value) ->
        @supported_model_tiers
        |> Map.fetch!(value)
        |> pool_tier_for()

      Map.has_key?(@supported_model_pool_tiers, value) ->
        Map.fetch!(@supported_model_pool_tiers, value)

      true ->
        value
    end
  end

  defp pool_tier_for(value) when is_atom(value), do: Map.get(@tier_to_pool, value, value)

  defp asset_sources(attrs, source) do
    %{}
    |> maybe_put_source(:path, attrs["path"], source)
    |> maybe_put_source(:content, attrs["content"], source)
  end

  defp attr_sources(attrs, source, key_map) do
    key_map
    |> Enum.reduce(%{}, fn {key, source_key}, acc ->
      if Map.has_key?(attrs, key) do
        Map.put(acc, source_key, source)
      else
        acc
      end
    end)
  end

  defp supported_model_pool_tier?(value) when is_atom(value),
    do: value in Map.values(@supported_model_pool_tiers)

  defp supported_model_pool_tier?(value) when is_binary(value),
    do: Map.has_key?(@supported_model_pool_tiers, value)

  defp supported_model_pool_tier?(_value), do: false

  defp maybe_put_source(sources, _key, nil, _source), do: sources
  defp maybe_put_source(sources, key, _value, source), do: Map.put(sources, key, source)

  defp maybe_put_attr(map, field, attrs, key) do
    if Map.has_key?(attrs, key) do
      Map.put(map, field, attrs[key])
    else
      map
    end
  end

  defp effective_source(sources) do
    if Enum.any?(sources, &(&1 == "override")), do: "override", else: "default"
  end

  defp source_label(source) when source in ["default", "override"], do: source
  defp source_label(_), do: "default"

  defp source_from_entry(entry) do
    entry.sources
    |> Map.values()
    |> effective_source()
  end

  defp diagnostic(source, path, reason, value \\ nil) do
    %Diagnostic{source: source_label(source), path: path, reason: reason, value: value}
  end

  defp stringify_keys(value) when is_map(value) do
    Map.new(value, fn {key, nested} -> {to_string(key), stringify_keys(nested)} end)
  end

  defp stringify_keys(value) when is_list(value), do: Enum.map(value, &stringify_keys/1)
  defp stringify_keys(value), do: value
end
