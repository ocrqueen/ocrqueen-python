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
    file=open("patent.pdf", "rb"),
    profile="advanced",
)
```

## Documentation

- Full API reference: <https://ocrqueen.com/docs>
- Python SDK guide: <https://ocrqueen.com/docs/sdks/python>
- Data retention & deletion: <https://ocrqueen.com/docs/data-retention>

## License

MIT — see [LICENSE](LICENSE).
