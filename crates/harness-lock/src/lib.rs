//! harness-lock: lock your agent into place.
//!
//! This crate is the published Rust entry point for harness-lock. It re-exports
//! [`harness_lock_core`], so `cargo add harness-lock` gives you the manifest,
//! lockfile, store, and tuning APIs under `harness_lock::…`. The same API is also
//! published under the shorter name [`hlock`](https://crates.io/crates/hlock).

pub use harness_lock_core::*;

#[cfg(test)]
mod tests {
    // The facade must expose the same modules and top-level items as the core crate.
    #[test]
    fn reexports_core_api() {
        let _ = std::any::type_name::<crate::Lockfile>();
        let _ = std::any::type_name::<crate::manifest::Manifest>();
        let _ = std::any::type_name::<crate::Tuner>();
        let _ = crate::sha256_text;
    }
}
