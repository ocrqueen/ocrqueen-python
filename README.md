# ocrqueen-python

Official Python SDK for the [OCRQueen](https://ocrqueen.com) document extraction API.

> 🚧 **Status:** Pre-release. APIs and surface area will change before `v1.0.0`.

## Installation

```bash
pip install ocrqueen
```

Requires Python 3.10 or newer.

## Quickstart

```python
from ocrqueen import OCRQueen

client = OCRQueen(api_key="pk_...")

with open("paper.pdf", "rb") as f:
    job = client.extract.create(file=f)

result = job.wait()
print(result.markdown)
```

Get an API key from [dashboard.ocrqueen.com](https://ocrqueen.com/dashboard/keys).

## Documentation

- Full API reference: <https://ocrqueen.com/docs>
- Python SDK guide: <https://ocrqueen.com/docs/sdks/python>

## License

MIT — see [LICENSE](LICENSE).
