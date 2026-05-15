# ocrqueen-python — Claude orientation

You are in the **official Python SDK** for OCRQueen. It's published to PyPI
as `ocrqueen`. This file is what you need to know to work here productively
without re-discovering decisions that were already made.

## What this is

Thin client around the OCRQueen HTTP API. Users do `pip install ocrqueen`,
then:

```python
from ocrqueen import OCRQueen
client = OCRQueen(api_key="pk_...")
job = client.extract.create(file=open("doc.pdf", "rb"))
result = client.jobs.wait(job)
```

Sibling repos (NOT included here):
- `ocrqueen/ocrqueen-node` — the matching Node/TypeScript SDK. Mirror this
  one's shape when adding features so the two stay parallel.
- `ocrqueen/openapi` — single source of truth for the API contract. Pull
  schema changes from here when wider refactors land.
- `ocrqueen/ocrqueen` — the API itself (private). NOT visible from this
  repo; you can only depend on the public HTTP contract.

## Stack

- Python ≥ 3.10. `pyproject.toml` is hatchling-built.
- Runtime dep: **just `httpx`**. Don't add more without a strong reason —
  every new dep is supply-chain risk for everyone who installs us.
- Dev: `pytest`, `respx` (HTTP mocking), `ruff` (lint + format), `mypy` (strict).
- src layout — `src/ocrqueen/...`. Tests in `tests/`.

## Public surface (don't change without thinking)

- `OCRQueen` — top-level client. Constructor reads `OCRQUEEN_API_KEY` env
  fallback. Has `.extract` and `.jobs` resource sub-objects (lazy init).
- `client.extract.create(file, profile, options, idempotency_key)` — POST /v1/extract
- `client.jobs.{get,list,cancel,wait}` — GET/DELETE /v1/jobs/*
- `verify_webhook(body, signature_header, secret=)` — HMAC-SHA256
  verifier for OCRQueen's outbound webhooks. Constant-time compare via
  `hmac.compare_digest`. Returns `False`, never raises.
- Error hierarchy: `OCRQueenError` → `APIError`, `APIConnectionError`,
  `APITimeoutError`, `AuthenticationError`, `BadRequestError`,
  `InsufficientBalanceError`, `NotFoundError`, `PermissionDeniedError`,
  `RateLimitError`, `ServerError`, `ValidationError`.

## Security invariants (DO NOT WEAKEN)

`src/ocrqueen/_http.py` is the security-critical file. Every invariant
has a test in `tests/test_http.py`. Each comment block in that file
explains the threat it mitigates.

- **I1** `base_url` MUST start with `https://`. Plain HTTP rejected.
  Applies to `OCRQUEEN_BASE_URL` env override too — no attacker-injected
  env can downgrade us to http.
- **I2** TLS verification is on. No `verify=False`, no agent override.
- **I3** `Authorization` header is set by us alone. `extra_headers`
  cannot override it.
- **I4** `api_key` is redacted in `repr()` and any error message.
- **I5** Redirects are NOT followed (`follow_redirects=False`).
- **I6** Every request has connect/read/write/pool timeouts.

API key format (`pk_<32-128 chars>` or legacy `pk_live_/pk_test_`) is
validated client-side so typos never reach the wire / third-party logs.

## Release flow

There is **no PyPI token anywhere**. Releases use OIDC Trusted Publishing
via the `pypi` GitHub Environment, with a required manual-approval gate.

To cut a release:

1. Bump version in BOTH `pyproject.toml` AND `src/ocrqueen/_version.py`
   to the new value. Update `CHANGELOG.md`. Open a PR; merge after CI.
2. From `main`: `git tag vX.Y.Z && git push origin vX.Y.Z`
3. The `Release` workflow runs `build` (CI gates + wheel build).
4. The `publish` job pauses for your approval in the `pypi` GitHub
   Environment.
5. After approval, the OIDC token is sent to PyPI, the package is
   published, and `actions/attest-build-provenance` attaches a
   Sigstore signature.

The release workflow REJECTS the publish if `pyproject.toml` version
doesn't match the tag — a typed-wrong tag can't ship a wrong version.

## Conventions

- All third-party GitHub Actions are pinned to a full commit SHA, not
  a tag. See comments in `.github/workflows/ci.yml` for rationale.
- Tests are organized by feature: `test_http.py`, `test_jobs.py`,
  `test_webhooks.py`, etc. One test per security invariant.
- mypy is `strict = true`; ruff includes `S` (bandit) rules.
- We re-export all public symbols in `src/ocrqueen/__init__.py`'s
  `__all__`. The smoke test enforces that nothing leaks into the
  public namespace without being declared there.

## Files NOT in version control

`.python-version`, `.venv/`, `__pycache__/`, secrets — see `.gitignore`.

## Where to look when something's wrong

- Test failure in CI: re-run locally with `pytest -q`. If you don't
  have the venv, `python -m venv .venv && source .venv/bin/activate
  && pip install -e ".[dev]"`.
- Type errors: `mypy src/ocrqueen`.
- Lint: `ruff check src tests` + `ruff format --check src tests`.
- Release fails at the publish step: check the `pypi` GitHub
  Environment exists and the PyPI Trusted Publisher binding points
  at THIS repo / `release.yml` / env `pypi`.

## Stuff that's NOT here yet

- No retry policy on transient errors. We surface `APITimeoutError`
  and `APIConnectionError` and let the caller decide. Adding a
  built-in retry should preserve idempotency (only retry on idempotent
  methods + Idempotency-Key).
- No async client. `httpx` supports it; we ship sync only for v0.x to
  keep the surface small. Add `AsyncOCRQueen` later if customers ask.
- No streaming response support (would matter for very-large extracts).
