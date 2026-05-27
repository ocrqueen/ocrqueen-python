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
text, tables, images, math, code, diagram graphs, and reference linking
— from a single unified pipeline. No profiles, no toggles.

## Quickstart

```python
from ocrqueen import OCRQueen

client = OCRQueen(api_key="pk_...")

with open("paper.pdf", "rb") as f:
    job = client.extract.create(file=f)

final = client.jobs.wait(job)
print(final.markdown)
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
```

### Fetching extracted images

Image blocks carry a stable proxy URL — it never expires until the
underlying object is purged by your retention window. `fetch_image()`
handles the 302 → signed-storage dance for you and returns raw bytes.

```python
final = client.jobs.wait(job)
for page in final.document["pages"]:
    for block in page["blocks"]:
        if block.get("kind") == "image":
            bytes_ = client.jobs.fetch_image(block["url"])
            open(f"{block['id']}.png", "wb").write(bytes_)
```

## Documentation

- Full API reference: <https://ocrqueen.com/docs>
- Python SDK guide: <https://ocrqueen.com/docs/sdks/python>
- Data retention & deletion: <https://ocrqueen.com/docs/data-retention>

## License

MIT — see [LICENSE](LICENSE).
