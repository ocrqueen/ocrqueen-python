"""Single source of truth for the SDK version.

Read by `pyproject.toml`'s build-time metadata AND by the HTTP layer's
`User-Agent` header so we can later rate-limit broken versions in the
API gateway without pushing a new SDK release.

Bump in lockstep with the `version` field in `pyproject.toml` — the CI
release workflow asserts the two match before publishing.
"""

from __future__ import annotations

__version__ = "0.6.0"
