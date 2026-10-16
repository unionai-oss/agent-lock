//! Content hashing helpers.

use sha2::{Digest, Sha256};

/// `sha256:<hex>` of raw bytes.
pub fn sha256_bytes(data: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(data);
    format!("sha256:{}", hex(&h.finalize()))
}

/// Hex digest (no prefix) of bytes.
pub fn sha256_hex(data: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(data);
    hex(&h.finalize())
}

/// `sha256:<hex>` of a string.
pub fn sha256_text(s: &str) -> String {
    sha256_bytes(s.as_bytes())
}

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

/// Deterministic, canonical JSON hash for a serde value ("sha256:" prefixed).
pub fn content_hash(v: &serde_json::Value) -> String {
    sha256_bytes(canon_json(v).as_bytes())
}

/// Canonical (sorted-key, compact) JSON of a serde value.
pub fn canon_json(v: &serde_json::Value) -> String {
    let r = crate::hash::sorted(v);
    serde_json::to_string(&r).unwrap_or_default()
}

/// Recursively sort object keys for deterministic serialization.
fn sorted(v: &serde_json::Value) -> serde_json::Value {
    match v {
        serde_json::Value::Object(map) => {
            let mut out = serde_json::Map::new();
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            for k in keys {
                out.insert(k.clone(), sorted(&map[k]));
            }
            serde_json::Value::Object(out)
        }
        serde_json::Value::Array(items) => {
            serde_json::Value::Array(items.iter().map(sorted).collect())
        }
        other => other.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deterministic() {
        let a = serde_json::json!({"b": 1, "a": [3, {"d": 4, "c": 5}]});
        let b = serde_json::json!({"a": [3, {"c": 5, "d": 4}], "b": 1});
        assert_eq!(content_hash(&a), content_hash(&b));
    }

    #[test]
    fn distinct() {
        let a = serde_json::json!({"x": 1});
        let b = serde_json::json!({"x": 2});
        assert_ne!(content_hash(&a), content_hash(&b));
    }
}
