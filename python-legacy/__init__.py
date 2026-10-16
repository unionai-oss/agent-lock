"""harness-lock — lock your agent into place.

Tune an agent stack (LLM assignment, harness, tools, skills, policies) against a
domain task pack, and write an ``harness.lock`` file that pins, hashes, and documents
the winning stack with the evidence for choosing it.

Layer 0 (CLI) and Layer 1 (Python API) live here. ``hlock.flyte`` (Layer 3)
exposes the tuning pipeline as composable Flyte tasks.
"""

from hlock.api import SearchSpace, load, lock
from harness.lockfile import Lockfile
from hlock.manifest import Budget, Manifest, Objective
from hlock.search import Stack
from hlock.tasks import TaskPack
from hlock.version import __version__

# Backwards-friendly alias: `Lock` refers to the lockfile object returned by lock().
Lock = Lockfile

__all__ = [
    "Budget",
    "Lock",
    "Lockfile",
    "Manifest",
    "Objective",
    "SearchSpace",
    "Stack",
    "TaskPack",
    "__version__",
    "load",
    "lock",
]
