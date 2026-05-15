"""OCRQueen — official Python SDK.

Public surface lives here; underscore-prefixed modules are private and
may change between patch releases. Re-exports use explicit `__all__` so
`from ocrqueen import *` is deterministic and we can't accidentally leak
an internal symbol.
"""

from __future__ import annotations

from ocrqueen._client import OCRQueen
from ocrqueen._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InsufficientBalanceError,
    NotFoundError,
    OCRQueenError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from ocrqueen._version import __version__

# Sorted to satisfy RUF022 — alphabetical, dunders first.
__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "InsufficientBalanceError",
    "NotFoundError",
    "OCRQueen",
    "OCRQueenError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServerError",
    "ValidationError",
    "__version__",
]
