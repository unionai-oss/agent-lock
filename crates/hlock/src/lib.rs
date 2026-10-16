//! hlock: the short name for [harness-lock](https://crates.io/crates/harness-lock).
//!
//! Re-exports [`harness_lock_core`], so `cargo add hlock` gives you the same manifest,
//! lockfile, store, and tuning APIs as `harness-lock`, under `hlock::…`.

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
