# ocrqueen-python

Official Python SDK for the [OCRQueen](https://ocrqueen.com) document and image extraction API.

> 🚧 **Status:** Pre-release. APIs and surface area will change before `v1.0.0`.

## Installation

```bash
pip install ocrqueen
```

Requires Python 3.10 or newer.

## Supported formats

| Category | Formats |
|---|---|
| Documents | **PDF** |
| Presentations | **PPTX**, **PPT** (PowerPoint) |
| Images | **PNG**, **JPEG**, **WebP**, **HEIC** / **HEIF** (iPhone photos) |

The API returns structured JSON + Markdown for every supported type —
text, tables, images, and (with `extraction_profile="advanced"`)
diagram graph extraction and image alt-text.

## Quickstart

```python
from ocrqueen import OCRQueen

client = OCRQueen(api_key="pk_...")

with open("paper.pdf", "rb") as f:
    job = client.extract.create(file=f)

result = client.jobs.wait(job)
print(result.result["markdown"])
```

Get an API key from [dashboard.ocrqueen.com](https://ocrqueen.com/dashboard/keys).

### Other file types

```python
# Slide decks — speaker notes are preserved
job = client.extract.create(file=open("pitch.pptx", "rb"))

# iPhone photos — HEIC handled natively, no conversion needed
job = client.extract.create(file=open("receipt.heic", "rb"))

# Scanned document images
job = client.extract.create(file=open("invoice.png", "rb"))

# Deeper extraction profile — diagrams, image alt-text, OCR on
# embedded text
job = client.extract.create(
    file=open("paper.pdf", "rb"),
    profile="advanced",
)
```

### Patent extraction (`domain="patent"`)

Route a PPTX or PDF through the patent-specific pipeline: region
classification (cover / abstract / drawings / claims / references),
Gemini cover parser, LibreOffice rasterisation for EMF/WMF figures,
cross-figure numeral resolution, and an honest per-stage
`faithfulness_score`. Billed flat at $0.05/page regardless of profile.

```python
job = client.extract.create(
    file=open("invention-disclosure.pptx", "rb"),
    options={"domain": "patent"},
)
result = client.jobs.wait(job).result        # response shape changes — discriminator is `domain`
patent = result                              # full PatentExtractionResponse
print(patent["source"]["input_kind"])        # "invention_disclosure" | "published_patent" | "unknown"
print(patent["extraction"]["faithfulness_score"])

# Figures carry a stable proxy URL — never expires until the underlying
# object is purged by your retention window. fetch_image() handles the
# 302 → signed-storage dance for you and returns raw bytes.
for fig in patent["drawings"]:
    bytes_ = client.jobs.fetch_image(fig["image_url"])
    open(f"{fig['figure_number'].replace(' ', '_')}.png", "wb").write(bytes_)
```

The same `fetch_image()` helper works for general-domain `ImageBlock`
URLs (`pages[].blocks[].url`) — useful for snapshotting all figures
from a job into your own pipeline.

## Documentation

- Full API reference: <https://ocrqueen.com/docs>
- Python SDK guide: <https://ocrqueen.com/docs/sdks/python>
- Data retention & deletion: <https://ocrqueen.com/docs/data-retention>

## License

MIT — see [LICENSE](LICENSE).
