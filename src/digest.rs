use sha2::{Digest, Sha256};

use crate::schema::ReviewRequest;

pub fn sha256_digest(bytes: impl AsRef<[u8]>) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes.as_ref());
    format!("sha256:{:x}", hasher.finalize())
}

pub fn request_digest(request: &ReviewRequest) -> Result<String, serde_json::Error> {
    serde_json::to_vec(request).map(sha256_digest)
}
