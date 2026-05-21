# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] — 2026-05-21

Fixes three SDK ↔ API contract bugs discovered during an end-to-end
smoke test against production. All three were silent failures — the
SDK didn't crash, it just returned empty / wrong fields.

### Fixed

- `ExtractJob.id` was always `""` because the SDK read `body["id"]`
  but the API returns `body["job_id"]`. Now reads `job_id`.
- `ExtractJob.result` was always `None`. The API returns the
  extraction under `document` (general domain) or `patent` (patent
  domain), not `result`. New explicit fields: `document`, `patent`,
  `markdown`, `cache_hit`, `domain`. The `result` property is kept
  as a legacy alias that dispatches on `domain`.
- `error_code` / `error_message` were read from flat keys but the
  API nests them under `error: {code, message}`. Now reads the
  nested shape.
- File uploads of `.pptx` (and other types where `mimetypes` returns
  octet-stream) were rejected by the server with `UNSUPPORTED_FILE_TYPE`.
  The SDK now ships its own MIME table and attaches an explicit
  `Content-Type` to the multipart part for `.pdf`, `.png`, `.jpg`,
  `.jpeg`, `.webp`, `.heic`, `.heif`, `.pptx`.

### Note for upgraders

The shape of `ExtractJob` changed: `result` is still readable (now
a property), but if you were destructuring `.result` directly into
a dict you may want to switch to `.document` / `.patent` so the
intent is explicit. `.raw` continues to hold the full server body
for advanced callers.

## [0.4.0] — 2026-05-21

Additive bump for Slice 8 + 9 — Figure Pipeline. SDK consumers gain
forward-compat for substantially-redesigned figure extraction on
`domain="patent"` responses. No SDK behavior change; the SDK
remains a thin HTTP client returning the API's JSON contract verbatim.

### Added (via OpenAPI re-dump)

On `PatentFigure`:
- `source_bbox`, `shape_cluster_inner_bbox` — per-shape and tighter-inner
  bbox for the new per-shape crop pipeline
- `parent_figure` — sub-figure linkage ("FIG. 4A" → "FIG. 4")
- `is_prior_art` — deterministic PRIOR ART stamp detection
- `extraction_expectation` — `Literal["LABELED_BLOCKS_ONLY",
  "WITH_CALLOUTS", "WITH_TOPOLOGY", "FREE_FORM"] | None`. Drives
  per-figure numerals-skip and faithfulness scoring on the API side.

On `ReferenceNumeral`: `confidence` (`high|medium|low`).

On `FlowchartNode` + `FlowchartEdge`: `confidence` (per-element).

On `FlowchartTopology`: `source` (`deterministic|vision`) —
distinguishes \$0-cost connector-graph-derived topology from
Vision-derived.

Schema-wide: new `text_source = "pptx_shape_cluster"` on general
document `ImageBlock`s synthesised from native PPTX shape clusters
(Slice 9 discovery layer).

10 new `PatentWarningCode` values covering figure / topology /
numerals / prior-art failure modes (see API CHANGELOG for the full
list).

### Customer impact

On the locked customer reference fixture (`patent_sample_US11847293.pptx`),
real-figure recall went from 0/4 to 4/4. FIG. 2 now ships as a
25-node, 24-edge, 4-swimlane Mermaid flowchart via the API's
deterministic-first topology path.

## [0.3.2] — 2026-05-20

Additive enum bump for Slice 12 — Patent Claims Parser. No SDK
behavior change; SDK consumers gain forward-compat for the new
warning codes the API now emits on `domain="patent"` responses.

### Added (via OpenAPI re-dump)
- `PatentWarningCode.CLAIMS_REGION_EMPTY`
- `PatentWarningCode.CLAIMS_EMPTY_BODIES_DETECTED`
- `PatentWarningCode.RESCUE_HALLUCINATED_CLAIM_DROPPED`

Plus additive schema additions (`AmendmentMarkupSpan`,
`MPFStructureBinding`, `ClaimCategory` enum, `ClaimType.MULTI_DEPENDENT`,
`ClaimType.UNKNOWN`, `ClaimEdge.dependency_kind`,
`ClaimEdge.alternative_group_id`, `PatentClaim.preamble: str | None`,
`PatentClaim.category`). Pinned v0.3.x SDKs deserialize the new
fields as `Optional` / `UNKNOWN` per the API's `_missing_` shim;
upgrading to 0.3.2 surfaces them through the result dict.

## [0.3.1] — 2026-05-20

Docs-only release. Refreshes the PyPI landing-page README with
patent-extraction examples + `fetch_image` usage. No runtime change.

## [0.3.0] — 2026-05-20

### Added
- `client.jobs.fetch_image(url_or_path)` — download bytes from the new
  image-proxy URLs that the API emits on patent figures
  (`drawings[i].image_url`) and general image blocks
  (`pages[].blocks[].url`). Performs the two-step auth → 302 → R2 dance
  so callers don't have to follow redirects themselves.

### Note
- `cost_usd` on extraction responses now reflects the customer billing
  rate (what the wallet debits), not the internal Gemini token cost.
  No SDK surface change.
- Patent extractions (`domain="patent"`) are now priced at $0.05/page
  (was $0.10/page) to align with the Advanced tier description.

## [0.2.1] — 2026-05-16

Metadata-only release. No runtime or API behaviour change.

### Changed
- Expanded `pyproject.toml` keywords from a PDF-focused set to cover every
  supported format and use case: `pptx`, `powerpoint`, `presentation-extraction`,
  `image-extraction`, `image-ocr`, `heic`, `pdf-to-json`, `pdf-to-markdown`,
  `document-extraction`, `ocr-api`, `structured-extraction`, `rag`. PyPI
  search indexes keywords, not READMEs — so even though the README
  documented all formats since v0.2.0, searches for "PPTX extraction Python" /
  "HEIC OCR" still missed us. Fixes that.

## [0.2.0] — 2026-05-16

### Added
- `client.jobs.purge(job_id)` — hard-erases a job's source bytes from
  object storage and clears the extracted result from the database. The
  job row remains as a billing tombstone (id, customer, page count,
  timestamps). Requires the new `jobs:write` scope on the API key;
  deliberately separate from `extract:write` so read-only keys can fetch
  results without being able to delete them. Idempotent — calling on an
  already-purged job is a no-op. Pairs with the new
  `result_retain_hours` extraction option (server-side; pass through
  `options=`) so customers can control how long extracted content
  lives on OCRQueen's servers after a job completes. Full contract:
  <https://ocrqueen.com/docs/data-retention>.
- README now documents every supported file type — **PDF**, **PPTX**,
  **PPT**, **PNG**, **JPEG**, **WebP**, **HEIC**, **HEIF**. The API has
  accepted all of these since v0.1.0 but only PDF was advertised, costing
  organic discoverability on PyPI search and Google.
- README "Other file types" snippet block with one example per
  category, plus an `profile="advanced"` example.

### Fixed
- README quickstart called `job.wait()` and `result.markdown` — neither
  exists. Corrected to `client.jobs.wait(job)` and
  `result.result["markdown"]`. The broken snippet was the first thing a
  new user saw on PyPI; switching to the working form unblocks fresh
  installs.

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
