pub(crate) fn redact_secret(text: &str, secret: Option<&str>) -> String {
    let Some(secret) = secret else {
        return text.to_string();
    };
    if secret.is_empty() {
        return text.to_string();
    }
    text.replace(secret, "<redacted>")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_exact_secret_value() {
        assert_eq!(
            redact_secret("token=abc123\n", Some("abc123")),
            "token=<redacted>\n"
        );
    }

    #[test]
    fn leaves_text_without_secret_unchanged() {
        assert_eq!(redact_secret("ok", None), "ok");
        assert_eq!(redact_secret("ok", Some("")), "ok");
    }
}
