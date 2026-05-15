"""OCRQueen — official Python SDK.

Public surface lives here; underscore-prefixed modules are private and
may change between patch releases. Re-exports use explicit `__all__` so
`from ocrqueen import *` is deterministic and we can't accidentally leak
an internal symbol.
"""

from __future__ import annotations

from ocrqueen._version import __version__

__all__ = [
    "__version__",
]
