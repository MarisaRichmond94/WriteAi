"""Re-export shim — the implementation moved to src/canonical.py so the
retrieval layer can reuse the same alias system (query-time alias
resolution, ENABLE_ALIAS_RESOLUTION). Server code keeps importing from
here unchanged."""

from src.canonical import *  # noqa: F401,F403
from src.canonical import Canonicalizer, Entity  # noqa: F401
