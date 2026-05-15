# Contributing

Thanks for considering a contribution. This repo follows the conventions of
the larger OCRQueen project; the bits specific to the Python SDK live here.

## Development setup

```bash
git clone git@github.com:ocrqueen/ocrqueen-python.git
cd ocrqueen-python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Run the gates that CI runs:

```bash
pytest -q
ruff check src tests
ruff format --check src tests
mypy src/ocrqueen
```

## Pull requests

- Branch from `main`. Direct push is blocked by branch protection.
- Every PR is reviewed by a code owner — see [.github/CODEOWNERS](.github/CODEOWNERS).
- Keep diffs focused. Security-sensitive files (`_http.py`, `_errors.py`)
  require extra scrutiny — flag the change in your PR description.

## Releases (maintainers only)

We publish to PyPI via **Trusted Publishing** — there is no PyPI API token
to leak. The release workflow ([.github/workflows/release.yml](.github/workflows/release.yml))
is the only path to publish.

To cut a release:

1. Open a PR that bumps both `pyproject.toml` and
   `src/ocrqueen/_version.py` to the new version, and updates
   `CHANGELOG.md`. The build job asserts the tag and `pyproject.toml`
   version match, so they must be in lockstep.
2. Merge the PR (squash) once CI passes.
3. From `main`:
   ```bash
   git pull origin main
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. The `Release` workflow runs the `build` job (CI gates + wheel build
   + metadata validation), then waits for **manual approval** in the
   `pypi` environment.
5. Approve the deployment in the GitHub Actions UI. The OIDC token is
   exchanged with PyPI and the package is published.
6. The final `sign` job attaches a Sigstore build-provenance
   attestation to the artifacts.

If something goes wrong between tagging and approval, you can just
**not approve** — nothing publishes. If a publish succeeds but the
version is broken, **do not delete it from PyPI** (you can't reuse the
version anyway); release a fixed `v0.1.1` instead.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.
