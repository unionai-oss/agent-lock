"""`import hlock` is the same API as `import harness_lock`."""

import harness_lock
import hlock


def test_hlock_exposes_the_same_public_names():
    assert hlock.__all__ == harness_lock.__all__
    for name in harness_lock.__all__:
        assert getattr(hlock, name) is getattr(harness_lock, name), name


def test_hlock_version_matches():
    assert hlock.__version__ == harness_lock.__version__
