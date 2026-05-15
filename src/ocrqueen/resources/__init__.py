"""Resource sub-modules grouped by API domain.

Each file in here exposes one Resource class that takes an
`HttpClient` in its constructor and exposes the domain's methods. The
top-level `OCRQueen` client instantiates these lazily.

Nothing in this package is part of the public surface — users access
resources via `client.extract`, `client.jobs`, etc., not by importing
from here directly. The classes are public-ish (their methods are what
customers call) but the import path is internal.
"""

from __future__ import annotations
