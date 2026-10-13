# book-translator

Translate English books (PDF / EPUB / TXT) into a bilingual PDF: each English
page is followed by its Chinese translation on the next page.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

The requirements include `opencv-python-headless` (used to clean scanned pages;
no model or training involved) and `fonttools` (to subset the CJK font embedded
in each Chinese page, which keeps the output PDF small).

The default backend, `claude-cli`, uses your logged-in [Claude Code](https://claude.com/claude-code)
CLI (`claude`), so no API key is needed. To use the Anthropic API instead:

```
export ANTHROPIC_API_KEY=sk-ant-...
python -m booktrans mybook.epub --backend api
```

## Use

```
python -m booktrans mybook.epub                 # -> mybook_bilingual.pdf
python -m booktrans mybook.pdf --pages 1-10     # -> mybook_bilingual pages 1-10.pdf
```

| Option | Meaning |
| --- | --- |
| `-o, --output` | output PDF path |
| `--backend NAME` | LLM provider: `claude-cli` (default), `api`, `qwen`, `qwen-intl`, `deepseek`, `openai-compatible` |
| `--model` | model name (default: the backend's default) |
| `--pages 1-20` | only this page range (a single number or `start-end`) |
| `--redo 9-10` | re-translate these pages even if cached |
| `--flat` | PDF input: plain-text Chinese pages instead of the original layout |
| `--ocr` | OCR scanned pages (needs a vision-capable backend) |
| `--ocr-backend`, `--ocr-model` | use a different backend / model for OCR |

Progress is cached in `<output>.cache.json`, so an interrupted run resumes
without re-paying for finished pages.

### Page layout (text PDFs)

For PDFs with a text layer, the Chinese page is a copy of the original page with
its English text replaced in place, so headings, bullets, side panels and images
keep their positions. The text is translated block by block (cached under `L<page>`
keys in the cache file). Use `--flat` for the older plain-text Chinese pages.
EPUB and TXT always use plain-text pages. Known limits: inline highlights such
as a boxed word, and dashed link underlines, stay in place without their text.

### Scanned pages with a text layer

Many scanned books carry a (rough) OCR text layer. Those pages are rebuilt on a
clean white page instead of being patched:

- **Paragraphs** are merged from lines by geometry (first-line indent, short last
  line, vertical gap, size jump). Each Chinese paragraph starts at the same height
  as its English paragraph; its bottom is free. One size factor per page keeps
  body, heading and note sizes consistent.
- **Tables** (3+ rows with 2+ aligned columns) are translated cell by cell and
  drawn in their original columns; wrapped cell text stays in its cell.
- **Figures, symbols and rules** are kept: OpenCV flattens the scan's paper tone
  and keeps only the dark ink (`figures.py`), with the English text erased and the
  Chinese drawn on top. Blocks the model answers `~` for (symbols, OCR noise) are
  left as they are.
- Limits: photographic plates are thresholded to line art; layouts that are not
  paragraphs or aligned tables fall back to paragraph flow.

### Scanned PDFs without a text layer

Pages with no text layer are detected automatically. To read them with
Claude's vision, add `--ocr`. It works with both built-in backends. These pages
use plain-text Chinese pages.

```
python -m booktrans scan.pdf --ocr --pages 1-5   # test first
```

OCR text is cached in `<output>.ocr.json` and is checked for each page, so
re-runs don't pay for images again. Vision OCR can occasionally misread a poor
scan, so spot-check a few pages. Use `--ocr-model` to pick a different model
for OCR than for translation.
Token usage of each run is appended to `<output>.usage.json`.

## Use as a library

The command line is a thin wrapper around `booktrans.pipeline.translate_book`,
which prints nothing and never exits the process, so a web service can call it:

```python
from booktrans.backends import make_backend
from booktrans.pipeline import count_pages, translate_book

pages = count_pages("book.pdf", "1-20")            # for a cost estimate
translator = make_backend("api")                   # ANTHROPIC_API_KEY, or pass your own backend
translate_book("book.pdf", "out.pdf", translator, pages="1-20",
               progress=lambda stage, done, total: print(stage, done, total))
```

`progress(stage, done, total)` is called as pages complete, with stage `scan`,
`ocr`, `translate` or `render`. Failed model calls (dropped connection, rate
limit) are retried with a growing delay and then raise `BackendError`; progress
is cached, so calling again resumes the job.

## Web service

A small web app lets others use the translator in a browser, with their own
Anthropic API key (the key is used for that one job, held in memory, and never
written to disk or logs).

```
pip install -r requirements-web.txt
python -m booktrans.web                 # http://127.0.0.1:8000
```

Upload a book, see the page count and an estimated cost, optionally preview 3
pages, then translate; the page shows progress and offers the PDF to download.
Jobs run in worker processes, survive a closed tab (the page resumes from
`localStorage`), and are deleted after 24 hours. Settings come from environment
variables: `BOOKTRANS_DATA` (data folder, default `data`), `BOOKTRANS_WORKERS`
(parallel jobs, default 2), `HOST`, `PORT`. Limits (upload size, pages per job,
retention) are arguments of `create_app` in `booktrans/web/app.py`.

API: `POST /api/jobs` (upload) → `POST /api/jobs/{id}/start` (`api_key`, `pages`,
`preview`, `ocr`) → `GET /api/jobs/{id}` (state, stage, done/total) →
`GET /api/jobs/{id}/download`; `DELETE /api/jobs/{id}` removes the files.

### Deploying

`Dockerfile`, `docker-compose.yml` (app + Caddy for automatic HTTPS) and `.env.example`
run the web service on any Linux server. See [docs/DEPLOY.md](docs/DEPLOY.md) for a
step-by-step guide for Alibaba Cloud / Tencent Cloud (international sites, Singapore or
Tokyo region).

## Switching API supplier

Any supplier that speaks the OpenAI chat protocol is one entry in `PROVIDERS`
(`backends/openai_compat.py`): endpoint, key variable, default text and vision models.
Built in: `qwen` / `qwen-intl` (key in `DASHSCOPE_API_KEY`), `deepseek` (`DEEPSEEK_API_KEY`,
no vision). For any other, use `--backend openai-compatible --model NAME` with
`BOOKTRANS_BASE_URL` and `BOOKTRANS_API_KEY`. `--ocr-model` picks the model for scanned pages.
The web page has a supplier menu; the user's key goes to the chosen supplier only.

## Adding a backend

Backends live in `booktrans/backends/`. Subclass `LLMBackend` and implement
`complete(system, user, max_tokens)` (text in, text out), then register it in
`BACKENDS` in `backends/__init__.py`; it appears in `--backend` automatically.
Vision is only needed for `--ocr`: set `supports_vision = True` and implement
`ocr_image(jpeg, prompt)`. With a text-only backend, use `--ocr-backend` to
OCR with a different provider than the one translating. Running `--ocr` with a
backend that has no vision stops immediately with a clear message.

## Project layout

```
booktrans/
  cli.py          argument parsing and printing; calls pipeline.translate_book
  pipeline.py     the whole job as a function, with a progress callback
  readers.py      PDF / EPUB / TXT -> list of page texts, page ranges
  ocr.py          OCR of scanned pages (via a vision backend)
  translate.py    translation, retry/fallback, on-disk cache
  layout.py       find text blocks / paragraphs / table cells on a PDF page, redraw it in Chinese
  figures.py      clean ink layer of a scan (OpenCV): keeps lines, curves and symbols
  writer.py       assemble the bilingual PDF
  web/            web service: app.py (API), jobs.py (job storage, worker), static/index.html
  usage.py        token usage tracking
  prompts.py      prompts sent to the model
  backends/       LLMBackend interface + claude-cli and api providers
tests/            pytest suite (uses a fake backend, no API calls)
```

## Tests

```
pip install -r requirements-dev.txt
python -m pytest tests
```

## License

MIT. This covers the code only; make sure you have the right to translate any book you process.
