"""hlock: make your agent harness pinnable, portable, and tunable.

``import hlock`` is the same API as ``import harness_lock``. The implementation lives
in the ``harness_lock`` package (and its compiled ``harness_lock._harness_lock``
module); this package re-exports it under the distribution's name.
"""

from harness_lock import *
from harness_lock import __all__, __version__  # noqa: F401
