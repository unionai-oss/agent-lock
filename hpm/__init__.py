"""harness-package-manager — lock your agent into place.

User-facing Python API, backed by the Rust core (compiled into ``hpm._hpm``).
"""

from ._hpm import (
    LOCK_VERSION,
    Budget,
    LockedAgent,
    Lockfile,
    Manifest,
    Objective,
    SearchSpace,
    __version__,
    load,
    lock,
    optimize,
    upgrade,
)

__all__ = [
    "LOCK_VERSION",
    "Budget",
    "LockedAgent",
    "Lockfile",
    "Manifest",
    "Objective",
    "SearchSpace",
    "__version__",
    "load",
    "lock",
    "optimize",
    "upgrade",
]
