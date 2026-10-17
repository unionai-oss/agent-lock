<p align="center">
  <img src="https://raw.githubusercontent.com/unionai-oss/hlock/main/docs/assets/logo.svg" alt="hlock logo" width="96">
</p>

# hlock

**Make your agent harness setup pinnable and portable.** Tune your agent stack against your own tasks, then pin the winner in a
`harness.lock`.

```bash
pip install hlock
```

```bash
hlock init --name demo --pack ./tasks   # write a starter harness.toml
hlock resolve                           # tune the search space -> harness.lock
hlock check                             # fail if harness.toml drifted from the lock
hlock run "clean ./data/orders.csv"     # run the locked agent
```

<p align="center">
  <img src="https://raw.githubusercontent.com/unionai-oss/hlock/main/docs/assets/quickstart.svg" alt="An hlock session: init, resolve, check, and run" width="640">
</p>

```python
import hlock

lock = hlock.resolve("harness.toml")
print(lock.summary())
```

`hlock` is the short name for [`harness-lock`](https://pypi.org/project/harness-lock/).
This package has no code of its own: each `hlock` release pins the identical
`harness-lock` release, so both names install the same thing, and `import hlock` is
the same API as `import harness_lock`.

- 📖 **Docs:** <https://unionai-oss.github.io/hlock/>
- 💻 **Source:** <https://github.com/unionai-oss/hlock>
- 🦀 **Rust:** `cargo add hlock`
