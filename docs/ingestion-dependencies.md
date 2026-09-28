# Ingestion dependencies

The supported ingestion profiles use the following concrete runtime inputs:

| Capability | Owner / use | Required profile | Failure behaviour |
| --- | --- | --- | --- |
| BeautifulSoup4 (`bs4`) | BMSTU and HSE HTML discovery and normalization | BMSTU, HSE | preflight failure |
| PyMuPDF (`fitz`) | primary PDF text/page extraction | BMSTU, HSE | fallback to pypdf, then typed parser failure |
| pypdf | portable PDF text fallback and metadata | BMSTU, HSE | typed parser failure if all readers are unavailable |
| pdfplumber | table extraction fallback and structured HSE plans | BMSTU, HSE | typed source/parser gap when the fallback is unavailable |
| Poppler `pdftotext` | BMSTU fixed-layout study-plan extraction | BMSTU | preflight failure; no empty successful plan |
| Playwright + Chromium | optional BMSTU browser fallback for JS/anti-bot sources | optional | named browser source gap; HTTP path remains canonical |

The PDF parsers share bounded policy values: 50 MB maximum body, 500 pages,
60 seconds for the Poppler subprocess, and 12 million extracted characters.
Oversized, malformed, or over-page documents are rejected before parser output
can be treated as a complete source.

Run the capability check without network access:

```powershell
python backend/scripts/preflight.py --profile bmstu --profile hse
```

The backend dependency graph is locked in `backend/uv.lock`. Use the lock for
clean-checkout installation (`uv sync --locked`) and keep `pyproject.toml` as
the authoritative direct dependency and optional-browser declaration.

Hash-addressed fixture bodies are byte-stable across Windows and Linux:
`.gitattributes` pins fixture JSON/HTML to LF and PDF files to binary. Do not
rewrite fixture line endings without regenerating the corresponding
`source_manifest.json` and MVP baseline hashes.

`openpyxl` was removed from the direct dependencies because no tracked runtime
or test module imports it. PyMuPDF, pdfplumber, and pypdf remain separate on
purpose: they serve different parser paths and the adapter fallbacks are
covered by the ingestion fixture suite.
