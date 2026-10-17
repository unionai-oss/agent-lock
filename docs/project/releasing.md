# Releasing

One tag publishes everything:

| Registry | Package | What it is |
|---|---|---|
| PyPI | [`hlock`](https://pypi.org/project/hlock/) | Wheels for Linux, macOS, and Windows, plus an sdist |
| PyPI | [`harness-lock`](https://pypi.org/project/harness-lock/) | Alias that pins the same `hlock` version |
| crates.io | [`harness-lock-core`](https://crates.io/crates/harness-lock-core) | The Rust library |
| crates.io | [`hlock`](https://crates.io/crates/hlock), [`harness-lock`](https://crates.io/crates/harness-lock) | Re-exports of the core (`harness-lock` is the alias) |

## Cutting a release

```bash
python scripts/set_version.py 0.2.0          # updates every version in the repo
python scripts/set_version.py --check        # prints 0.2.0
# open a PR, merge it once CI is green, then:
git switch main && git pull
git tag v0.2.0 && git push origin v0.2.0
```

Both publish workflows refuse to run if the tag doesn't match the version in
`Cargo.toml`.

The full checklist, one-time registry setup, and recovery steps are in
[RELEASING.md](https://github.com/unionai-oss/hlock/blob/main/RELEASING.md).
