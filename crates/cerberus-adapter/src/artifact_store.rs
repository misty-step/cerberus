use crate::AdapterError;
use cerberus_schema::ReviewRunArtifact;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub trait ReviewRunArtifactStore {
    fn put(&self, artifact: &ReviewRunArtifact) -> Result<PathBuf, AdapterError>;
    fn get(&self, run_id: &str) -> Result<ReviewRunArtifact, AdapterError>;
}

#[derive(Debug, Clone)]
pub struct FileReviewRunArtifactStore {
    root: PathBuf,
}

impl FileReviewRunArtifactStore {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn artifact_path(&self, run_id: &str) -> Result<PathBuf, AdapterError> {
        validate_safe_run_id(run_id)?;
        Ok(self.root.join("review-runs").join(format!("{run_id}.json")))
    }
}

impl ReviewRunArtifactStore for FileReviewRunArtifactStore {
    fn put(&self, artifact: &ReviewRunArtifact) -> Result<PathBuf, AdapterError> {
        let path = self.artifact_path(&artifact.run_id)?;
        artifact.validate()?;
        let mut bytes = serde_json::to_vec_pretty(artifact)?;
        bytes.push(b'\n');

        let directory = path
            .parent()
            .expect("artifact path always has a review-runs directory");
        fs::create_dir_all(directory).map_err(|source| io_error(directory, source))?;

        let tmp_path = temp_path_for(&path);
        if let Err(error) = write_new_file(&tmp_path, &bytes) {
            return Err(error);
        }
        if let Err(error) = link_into_place(&tmp_path, &path) {
            let _ = fs::remove_file(&tmp_path);
            return Err(error);
        }
        fs::remove_file(&tmp_path).map_err(|source| io_error(&tmp_path, source))?;

        Ok(path)
    }

    fn get(&self, run_id: &str) -> Result<ReviewRunArtifact, AdapterError> {
        let path = self.artifact_path(run_id)?;
        let raw = fs::read_to_string(&path).map_err(|source| io_error(&path, source))?;
        let artifact: ReviewRunArtifact = serde_json::from_str(&raw)?;
        artifact.validate()?;
        if artifact.run_id != run_id {
            return Err(AdapterError::ArtifactRunIdMismatch {
                expected: run_id.to_string(),
                actual: artifact.run_id,
            });
        }
        Ok(artifact)
    }
}

fn validate_safe_run_id(run_id: &str) -> Result<(), AdapterError> {
    let mut chars = run_id.chars();
    let Some(first) = chars.next() else {
        return Err(AdapterError::UnsafeArtifactRunId {
            run_id: run_id.to_string(),
        });
    };
    if !first.is_ascii_alphanumeric() {
        return Err(AdapterError::UnsafeArtifactRunId {
            run_id: run_id.to_string(),
        });
    }
    if !chars.all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.')) {
        return Err(AdapterError::UnsafeArtifactRunId {
            run_id: run_id.to_string(),
        });
    }
    Ok(())
}

fn temp_path_for(path: &Path) -> PathBuf {
    let file_name = path
        .file_name()
        .expect("artifact path always has a file name")
        .to_string_lossy();
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    path.with_file_name(format!("{file_name}.tmp-{}-{nanos}", std::process::id()))
}

fn write_new_file(path: &Path, bytes: &[u8]) -> Result<(), AdapterError> {
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|source| io_error(path, source))?;
    file.write_all(bytes)
        .map_err(|source| io_error(path, source))
}

fn link_into_place(tmp_path: &Path, final_path: &Path) -> Result<(), AdapterError> {
    fs::hard_link(tmp_path, final_path).map_err(|source| {
        if source.kind() == std::io::ErrorKind::AlreadyExists {
            AdapterError::ArtifactAlreadyExists {
                path: final_path.to_path_buf(),
            }
        } else {
            io_error(final_path, source)
        }
    })
}

fn io_error(path: impl AsRef<Path>, source: std::io::Error) -> AdapterError {
    AdapterError::ArtifactStoreIo {
        path: path.as_ref().to_path_buf(),
        source,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_core::{default_config, review};
    use cerberus_schema::{ReviewRequest, SchemaError};

    const LOCAL_DIFF_REQUEST: &str =
        include_str!("../../../fixtures/review-request/local-diff.json");

    #[test]
    fn artifact_store_persists_and_replays_valid_review_run_artifact() {
        let root = temp_root("valid-round-trip");
        let store = FileReviewRunArtifactStore::new(&root);
        let artifact = fixture_artifact();

        let path = store.put(&artifact).expect("artifact persists");
        assert_eq!(
            path,
            store.artifact_path(&artifact.run_id).expect("safe id")
        );
        assert!(path.exists());

        let replayed = store.get(&artifact.run_id).expect("artifact replays");
        assert_eq!(replayed, artifact);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn artifact_store_rejects_malformed_artifact_before_persisting() {
        let root = temp_root("malformed-before-persist");
        let store = FileReviewRunArtifactStore::new(&root);
        let mut artifact = fixture_artifact();
        let path = store.artifact_path(&artifact.run_id).expect("safe id");
        artifact.stats.total += 1;

        let error = store.put(&artifact).expect_err("mutated artifact fails");

        assert!(matches!(
            error,
            AdapterError::Schema(SchemaError::Inconsistent { field: "stats" })
        ));
        assert!(!path.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn artifact_store_refuses_to_overwrite_existing_receipt() {
        let root = temp_root("no-overwrite");
        let store = FileReviewRunArtifactStore::new(&root);
        let artifact = fixture_artifact();

        let path = store.put(&artifact).expect("first write succeeds");
        let error = store.put(&artifact).expect_err("second write fails");

        assert!(matches!(
            error,
            AdapterError::ArtifactAlreadyExists { path: existing } if existing == path
        ));
        assert_eq!(
            store
                .get(&artifact.run_id)
                .expect("original artifact replays"),
            artifact
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn artifact_store_rejects_unsafe_run_ids() {
        let root = temp_root("unsafe-run-id");
        let store = FileReviewRunArtifactStore::new(&root);
        let mut artifact = fixture_artifact();
        artifact.run_id = "../escape".to_string();

        assert!(matches!(
            store.put(&artifact),
            Err(AdapterError::UnsafeArtifactRunId { .. })
        ));
        assert!(matches!(
            store.get("../escape"),
            Err(AdapterError::UnsafeArtifactRunId { .. })
        ));
        assert!(matches!(
            store.artifact_path(".hidden-run"),
            Err(AdapterError::UnsafeArtifactRunId { .. })
        ));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn artifact_store_rejects_corrupt_persisted_json_on_replay() {
        let root = temp_root("corrupt-json");
        let store = FileReviewRunArtifactStore::new(&root);
        let artifact = fixture_artifact();
        let path = store.artifact_path(&artifact.run_id).expect("safe id");
        fs::create_dir_all(path.parent().expect("parent exists")).expect("create store dir");
        fs::write(&path, b"{not json").expect("write corrupt json");

        assert!(matches!(
            store.get(&artifact.run_id),
            Err(AdapterError::Serialization(_))
        ));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn artifact_store_rejects_tampered_persisted_artifact_on_replay() {
        let root = temp_root("tampered-replay");
        let store = FileReviewRunArtifactStore::new(&root);
        let artifact = fixture_artifact();
        let path = store.put(&artifact).expect("artifact persists");
        let mut json: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&path).expect("read stored artifact"))
                .expect("artifact json parses");
        json["stats"]["total"] = serde_json::json!(999);
        fs::write(
            &path,
            serde_json::to_vec_pretty(&json).expect("serialize tampered json"),
        )
        .expect("write tampered artifact");

        let error = store
            .get(&artifact.run_id)
            .expect_err("tampered artifact fails");

        assert!(matches!(
            error,
            AdapterError::Schema(SchemaError::Inconsistent { field: "stats" })
        ));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn artifact_store_rejects_run_id_mismatch_on_replay() {
        let root = temp_root("run-id-mismatch");
        let store = FileReviewRunArtifactStore::new(&root);
        let artifact = fixture_artifact();
        let path = store.artifact_path("review-run-other").expect("safe id");
        fs::create_dir_all(path.parent().expect("parent exists")).expect("create store dir");
        fs::write(
            &path,
            serde_json::to_vec_pretty(&artifact).expect("serialize artifact"),
        )
        .expect("write artifact under wrong id");

        assert!(matches!(
            store.get("review-run-other"),
            Err(AdapterError::ArtifactRunIdMismatch { .. })
        ));
        let _ = fs::remove_dir_all(root);
    }

    fn fixture_artifact() -> ReviewRunArtifact {
        let request: ReviewRequest =
            serde_json::from_str(LOCAL_DIFF_REQUEST).expect("request fixture parses");
        review(&request, &default_config()).expect("core review succeeds")
    }

    fn temp_root(name: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "cerberus-artifact-store-{name}-{}-{nanos}",
            std::process::id()
        ))
    }
}
