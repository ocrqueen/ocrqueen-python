"""Smoke tests — confirm the package installs + imports cleanly.

These run before anything else in CI; if they fail, the package is broken
at the most fundamental level and no other test result is meaningful.
"""

from __future__ import annotations


def test_package_imports() -> None:
    """The top-level module must import without side effects."""
    import ocrqueen  # noqa: F401


def test_version_is_a_string() -> None:
    """`__version__` exists and looks like a version string.

    We don't pin to a specific value — that would force every release to
    touch this test. We just assert the shape.
    """
    import ocrqueen

    assert isinstance(ocrqueen.__version__, str)
    assert ocrqueen.__version__.count(".") >= 1, ocrqueen.__version__


def test_no_accidental_private_reexports() -> None:
    """The public surface should NOT leak underscore-prefixed modules.

    A `from ocrqueen import *` should only pull symbols listed in
    `__all__`. This guards against future PRs that absent-mindedly add
    a top-level `from ocrqueen._http import HttpClient` and inadvertently
    promote a private symbol to public API.

    We only check symbols whose canonical home is `ocrqueen` itself
    (looking at the module's source via `inspect`). That filters out
    side-effect names like `annotations` from `__future__`, which is a
    Python-language artifact, not real public API.
    """
    import inspect
    import types

    import ocrqueen

    declared = set(ocrqueen.__all__)
    leaked: list[str] = []
    for name in dir(ocrqueen):
        if name.startswith("_"):
            continue
        value = getattr(ocrqueen, name)
        # Submodules (`ocrqueen.resources`, etc.) are inherently
        # importable in Python — accept them as organizational, not as
        # leaked API surface. We only check NAMED entities (classes,
        # functions, constants) against `__all__`.
        if isinstance(value, types.ModuleType):
            continue
        origin = inspect.getmodule(value)
        if origin is None or not origin.__name__.startswith("ocrqueen"):
            continue
        if name not in declared:
            leaked.append(name)
    assert not leaked, f"public attrs not in __all__: {sorted(leaked)}"
