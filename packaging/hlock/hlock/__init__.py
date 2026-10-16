"""hlock: the short name for harness-lock.

``import hlock`` is the same API as ``import harness_lock``; this package only
re-exports it. Installing ``hlock`` installs the matching ``harness-lock`` release.
"""

from harness_lock import *
from harness_lock import __all__, __version__  # noqa: F401
