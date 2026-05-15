# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-15

First usable release. The v0.0.0 placeholder was a name claim only.

### Added
- `client.jobs.get(job_id)` — fetch a single job.
- `client.jobs.list(status=, limit=, cursor=)` — paginated listing.
- `client.jobs.cancel(job_id)` — cancel a queued or running job.
- `client.jobs.wait(job_or_id, timeout_seconds=, poll_interval_seconds=, max_poll_interval_seconds=)`
  — exponential-backoff polling until terminal status.
- `ocrqueen.verify_webhook(body, signature_header, secret=)` — public
  helper for verifying OCRQueen webhook deliveries. Constant-time HMAC
  comparison; returns False on every malformed-input path (never raises).

### Notes
- All v0.0.x callers should be able to upgrade transparently — no
  breaking changes to existing APIs.

## [0.0.0] — 2026-05-15

### Added
- Initial package scaffold (`pyproject.toml`, src layout, lint + type config).
- HTTP foundation with security defaults (HTTPS-only base_url, TLS
  verification, redacted api_key, no auto-redirects, per-phase timeouts).
- `client.extract.create(file=)` — submit a document for extraction.

## Notes on versioning

Pre-1.0 the patch number may carry breaking changes. The minor number
tracks visible API surface. Once we hit `1.0.0`, we follow strict SemVer.

## Security advisories

Security fixes are documented in the relevant version's notes with a
**SECURITY:** prefix. See [SECURITY.md](SECURITY.md) for how to report a
vulnerability.
