"""harness-package-manager — lock your agent into place.

Tune an agent stack (LLM assignment, harness, tools, skills, policies) against a
domain task pack, and write an ``agent.lock`` file that pins, hashes, and documents
the winning stack with the evidence for choosing it.

Layer 0 (CLI) and Layer 1 (Python API) live here. ``hpm.flyte`` (Layer 3)
exposes the tuning pipeline as composable Flyte tasks.
"""

from hpm.api import SearchSpace, load, lock
from hpm.lockfile import Lockfile
from hpm.manifest import Budget, Manifest, Objective
from hpm.search import Stack
from hpm.tasks import TaskPack
from hpm.version import __version__

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
