"""agent-lock — lock your agent into place.

Tune an agent stack (LLM assignment, harness, tools, skills, policies) against a
domain task pack, and write an ``hpm.lock`` file that pins, hashes, and documents
the winning stack with the evidence for choosing it.

Layer 0 (CLI) and Layer 1 (Python API) live here. ``al.flyte`` (Layer 3)
exposes the tuning pipeline as composable Flyte tasks.
"""

from al.api import SearchSpace, load, lock
from hpm.lockfile import Lockfile
from al.manifest import Budget, Manifest, Objective
from al.search import Stack
from al.tasks import TaskPack
from al.version import __version__

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
