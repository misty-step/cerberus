use std::env;

pub(crate) const PROVIDER_BUDGET_ACK_ENV: &str = "CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK";

pub(crate) fn provider_budget_acknowledged() -> bool {
    env::var(PROVIDER_BUDGET_ACK_ENV)
        .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
        .unwrap_or(false)
}
