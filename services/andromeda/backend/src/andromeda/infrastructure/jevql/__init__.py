"""Optional embedded-first jevQL infrastructure boundary.

No jevQL SDK is imported at module import time. The default application path
continues to use materialized deterministic analytics.
"""

from .adapter import JevQLAdapter
from .config import JevQLConfig, JevQLMode
from .transport import EmbeddedTransport, SharedServiceTransport

__all__ = [
    "EmbeddedTransport",
    "JevQLAdapter",
    "JevQLConfig",
    "JevQLMode",
    "SharedServiceTransport",
]
