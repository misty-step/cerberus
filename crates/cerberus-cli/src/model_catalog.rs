use anyhow::{bail, Context, Result};
use cerberus_schema::{
    HarnessModelMatrix, ModelCandidate, ModelCatalogSnapshot, MODEL_CANDIDATE_VERSION,
};
use serde_json::Value;
use std::collections::BTreeMap;

pub fn refresh_openrouter_matrix(
    matrix: &HarnessModelMatrix,
    raw_catalog: &str,
    catalog_source: &str,
    observed_at: &str,
) -> Result<HarnessModelMatrix> {
    let catalog = OpenRouterCatalog::parse(raw_catalog)?;
    let mut refreshed = matrix.clone();
    refreshed.observed_at = observed_at.to_string();
    refreshed.models = matrix
        .models
        .iter()
        .map(|model| catalog.refresh_model(model, catalog_source, observed_at))
        .collect::<Result<Vec<_>>>()?;
    refreshed.validate()?;
    Ok(refreshed)
}

struct OpenRouterCatalog {
    models: BTreeMap<String, Value>,
}

impl OpenRouterCatalog {
    fn parse(raw_catalog: &str) -> Result<Self> {
        let value: Value =
            serde_json::from_str(raw_catalog).context("failed to parse catalog JSON")?;
        let data = value
            .get("data")
            .and_then(Value::as_array)
            .context("catalog is missing data array")?;
        let mut models = BTreeMap::new();
        for row in data {
            let id = row
                .get("id")
                .and_then(Value::as_str)
                .context("catalog model row is missing id")?;
            models.insert(id.to_string(), row.clone());
        }
        Ok(Self { models })
    }

    fn refresh_model(
        &self,
        previous_model: &ModelCandidate,
        catalog_source: &str,
        observed_at: &str,
    ) -> Result<ModelCandidate> {
        let row = self.models.get(&previous_model.model_id).with_context(|| {
            format!(
                "catalog source did not contain requested model {:?}",
                previous_model.model_id
            )
        })?;
        let pricing = row.get("pricing").with_context(|| {
            format!(
                "catalog model {:?} is missing pricing object",
                previous_model.model_id
            )
        })?;
        let top_provider = row.get("top_provider").with_context(|| {
            format!(
                "catalog model {:?} is missing top_provider object",
                previous_model.model_id
            )
        })?;
        let context_length = u64_field(row, &previous_model.model_id, "context_length")?;
        let max_completion_tokens = u64_field(
            top_provider,
            &previous_model.model_id,
            "max_completion_tokens",
        )?;
        let input_usd_per_m = usd_per_m(pricing, &previous_model.model_id, "prompt")?;
        let output_usd_per_m = usd_per_m(pricing, &previous_model.model_id, "completion")?;
        let cache_read_usd_per_m =
            optional_usd_per_m(pricing, &previous_model.model_id, "input_cache_read")?;
        let supported_parameters =
            string_array(row, &previous_model.model_id, "supported_parameters")?;

        let previous = if model_facts_changed(
            previous_model,
            context_length,
            max_completion_tokens,
            input_usd_per_m,
            output_usd_per_m,
            cache_read_usd_per_m,
        ) {
            Some(ModelCatalogSnapshot {
                observed_at: previous_model.catalog_observed_at.clone(),
                context_length: previous_model.context_length,
                max_completion_tokens: previous_model.max_completion_tokens,
                input_usd_per_m: previous_model.input_usd_per_m,
                output_usd_per_m: previous_model.output_usd_per_m,
                cache_read_usd_per_m: previous_model.cache_read_usd_per_m,
            })
        } else {
            previous_model.previous.clone()
        };

        let refreshed = ModelCandidate {
            schema_version: MODEL_CANDIDATE_VERSION.to_string(),
            model_id: previous_model.model_id.clone(),
            provider: previous_model.provider.clone(),
            context_length,
            max_completion_tokens,
            input_usd_per_m,
            output_usd_per_m,
            cache_read_usd_per_m,
            supported_parameters,
            catalog_source: catalog_source.to_string(),
            catalog_observed_at: observed_at.to_string(),
            previous,
        };
        refreshed.validate()?;
        Ok(refreshed)
    }
}

fn model_facts_changed(
    previous_model: &ModelCandidate,
    context_length: u64,
    max_completion_tokens: u64,
    input_usd_per_m: f64,
    output_usd_per_m: f64,
    cache_read_usd_per_m: Option<f64>,
) -> bool {
    previous_model.context_length != context_length
        || previous_model.max_completion_tokens != max_completion_tokens
        || previous_model.input_usd_per_m != input_usd_per_m
        || previous_model.output_usd_per_m != output_usd_per_m
        || previous_model.cache_read_usd_per_m != cache_read_usd_per_m
}

fn u64_field(value: &Value, model_id: &str, field: &'static str) -> Result<u64> {
    value.get(field).and_then(Value::as_u64).with_context(|| {
        format!("catalog model {model_id:?} field {field:?} is missing or not an unsigned integer")
    })
}

fn usd_per_m(value: &Value, model_id: &str, field: &'static str) -> Result<f64> {
    let per_token = value
        .get(field)
        .and_then(Value::as_str)
        .with_context(|| {
            format!("catalog model {model_id:?} pricing field {field:?} is missing or not a string")
        })?
        .parse::<f64>()
        .with_context(|| {
            format!("catalog model {model_id:?} pricing field {field:?} is not numeric")
        })?;
    if !per_token.is_finite() || per_token < 0.0 {
        bail!(
            "catalog model {model_id:?} pricing field {field:?} must be a non-negative finite number"
        );
    }
    Ok(round_usd_per_m(per_token * 1_000_000.0))
}

fn optional_usd_per_m(value: &Value, model_id: &str, field: &'static str) -> Result<Option<f64>> {
    if value.get(field).is_none() {
        return Ok(None);
    }
    usd_per_m(value, model_id, field).map(Some)
}

fn round_usd_per_m(value: f64) -> f64 {
    (value * 1_000_000_000.0).round() / 1_000_000_000.0
}

fn string_array(value: &Value, model_id: &str, field: &'static str) -> Result<Vec<String>> {
    let Some(values) = value.get(field) else {
        return Ok(vec![]);
    };
    let values = values
        .as_array()
        .with_context(|| format!("catalog model {model_id:?} field {field:?} is not an array"))?;
    values
        .iter()
        .map(|value| {
            value.as_str().map(str::to_string).with_context(|| {
                format!("catalog model {model_id:?} field {field:?} contains a non-string value")
            })
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const MATRIX: &str = include_str!("../../../fixtures/evals/harness-model-matrix.json");
    const CATALOG: &str =
        include_str!("../../../fixtures/evals/openrouter-models-catalog-minimal.json");

    #[test]
    fn model_catalog_refreshes_matrix_and_preserves_previous_snapshot() {
        let matrix: HarnessModelMatrix = serde_json::from_str(MATRIX).expect("matrix parses");
        let checked_glm = matrix
            .models
            .iter()
            .find(|model| model.model_id == "z-ai/glm-5.2")
            .expect("glm model exists");
        assert_eq!(checked_glm.max_completion_tokens, 131_072);
        assert_eq!(checked_glm.output_usd_per_m, 4.1);
        assert_eq!(checked_glm.cache_read_usd_per_m, Some(0.2));
        assert_eq!(
            checked_glm
                .previous
                .as_ref()
                .expect("previous snapshot")
                .max_completion_tokens,
            65_536
        );
        assert_eq!(
            checked_glm
                .previous
                .as_ref()
                .expect("previous snapshot")
                .output_usd_per_m,
            3.2
        );

        let mut stale_matrix = matrix.clone();
        let stale_glm = stale_matrix
            .models
            .iter_mut()
            .find(|model| model.model_id == "z-ai/glm-5.2")
            .expect("stale glm model exists");
        stale_glm.context_length = 1_048_576;
        stale_glm.max_completion_tokens = 65_536;
        stale_glm.input_usd_per_m = 1.2;
        stale_glm.output_usd_per_m = 3.2;
        stale_glm.cache_read_usd_per_m = Some(0.2);
        stale_glm.catalog_observed_at = "2026-06-18T18:20:00Z".to_string();
        stale_glm.previous = None;

        let refreshed_from_stale = refresh_openrouter_matrix(
            &stale_matrix,
            CATALOG,
            "fixtures/evals/openrouter-models-catalog-minimal.json",
            "2026-06-19-live",
        )
        .expect("stale catalog refresh succeeds");
        let refreshed_stale_glm = refreshed_from_stale
            .models
            .iter()
            .find(|model| model.model_id == "z-ai/glm-5.2")
            .expect("refreshed stale glm model exists");
        assert_eq!(refreshed_stale_glm.max_completion_tokens, 131_072);
        assert_eq!(
            refreshed_stale_glm
                .previous
                .as_ref()
                .expect("previous snapshot")
                .max_completion_tokens,
            65_536
        );
        assert_eq!(
            refreshed_stale_glm
                .previous
                .as_ref()
                .expect("previous snapshot")
                .output_usd_per_m,
            3.2
        );

        let refreshed = refresh_openrouter_matrix(
            &matrix,
            CATALOG,
            "fixtures/evals/openrouter-models-catalog-minimal.json",
            "2026-06-19-live",
        )
        .expect("catalog refresh succeeds");

        refreshed.validate().expect("refreshed matrix validates");
        assert_eq!(refreshed.observed_at, "2026-06-19-live");
        assert_eq!(refreshed.models.len(), matrix.models.len());
        let kimi = refreshed
            .models
            .iter()
            .find(|model| model.model_id == "moonshotai/kimi-k2.7-code")
            .expect("kimi model exists");
        assert_eq!(kimi.catalog_observed_at, "2026-06-19-live");
        assert_eq!(kimi.context_length, 262_144);
        assert_eq!(kimi.max_completion_tokens, 16_384);
        assert_eq!(kimi.input_usd_per_m, 0.74);
        assert_eq!(kimi.output_usd_per_m, 3.5);
        assert_eq!(kimi.cache_read_usd_per_m, Some(0.15));
        assert!(kimi
            .supported_parameters
            .contains(&"structured_outputs".to_string()));
        assert_eq!(
            kimi.previous
                .as_ref()
                .expect("previous snapshot")
                .observed_at,
            "2026-06-18"
        );

        let glm = refreshed
            .models
            .iter()
            .find(|model| model.model_id == "z-ai/glm-5.2")
            .expect("glm model exists");
        assert_eq!(glm.max_completion_tokens, 131_072);
        assert!((glm.output_usd_per_m - 4.1).abs() < 0.000_001);
        assert_eq!(glm.cache_read_usd_per_m, Some(0.2));
        assert_eq!(
            glm.previous
                .as_ref()
                .expect("previous snapshot")
                .max_completion_tokens,
            65_536
        );
        assert_eq!(
            glm.previous
                .as_ref()
                .expect("previous snapshot")
                .output_usd_per_m,
            3.2
        );
    }

    #[test]
    fn model_catalog_errors_when_requested_model_is_missing() {
        let mut matrix: HarnessModelMatrix = serde_json::from_str(MATRIX).expect("matrix parses");
        matrix.models[0].model_id = "missing/model".to_string();

        let error = refresh_openrouter_matrix(&matrix, CATALOG, "fixture", "2026-06-18")
            .expect_err("missing model is rejected");

        assert!(error.to_string().contains("missing/model"));
    }

    #[test]
    fn model_catalog_errors_when_required_pricing_is_missing() {
        let matrix: HarnessModelMatrix = serde_json::from_str(MATRIX).expect("matrix parses");
        let broken = CATALOG.replace("\"completion\": \"0.0000041\",", "");

        let error = refresh_openrouter_matrix(&matrix, &broken, "fixture", "2026-06-18")
            .expect_err("missing pricing is rejected");

        let message = error.to_string();
        assert!(message.contains("z-ai/glm-5.2"));
        assert!(message.contains("completion"));
    }
}
