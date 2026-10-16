# hlock

`hlock` is the short name for [`harness-lock`](https://pypi.org/project/harness-lock/):
lock your agent into place.

```bash
pip install hlock          # same as: pip install harness-lock
hlock --help
```

```python
import hlock               # same API as: import harness_lock
```

This package has no code of its own. Each `hlock` release pins the identical
`harness-lock` release, so the two names always install the same thing.
Documentation and source: <https://github.com/unionai-oss/harness-lock>.
