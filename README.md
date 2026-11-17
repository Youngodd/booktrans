# book-translator

Translate books (PDF / EPUB / Word / Markdown / TXT) from any widely used language into another with AI,
and write the result as PDF, EPUB, Word or Markdown.
The book's language is detected automatically; you choose the target language and
whether the PDF is bilingual (each original page followed by its translation) or
holds the translation only.

## Download

**Windows desktop app** — no Python or command line needed.

| | |
| --- | --- |
| Download | [BookTranslator-Setup-0.1.33.exe](https://github.com/Youngodd/booktrans/releases/download/v0.1.33/BookTranslator-Setup-0.1.33.exe) |
| Version | 0.1.33 (built 2026-11-15) |
| Size | 82 MB |
| SHA-256 | `9799539a1d70d479faca1e779b52c26294bc5c118ad159be1f7aa4929f71b19a` |
| Needs | Windows 10 or 11 (64-bit), an internet connection, and an API key from Anthropic, Qwen (Alibaba Cloud) or DeepSeek |

All versions are on the [Releases page](https://github.com/Youngodd/booktrans/releases). There is no Mac build yet; on a Mac, use the
command line below.

1. Run the downloaded file. It installs for your user only and needs no administrator rights.
2. Windows may show "Windows protected your PC" because the app is not code-signed (a certificate costs money).
   Click **More info**, then **Run anyway**. To check the file first, compare its SHA-256 with the one above
   (PowerShell: `Get-FileHash .\BookTranslator-Setup-0.1.33.exe`).
3. Open **Book Translator**, choose your provider, and paste your API key once. The key is kept in Windows Credential Manager. Your
   book goes only to the provider you chose; the app has no server of its own and collects nothing.

Your half-translated books are kept when you uninstall, so a reinstall does not lose them.

## Setup (command line)

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

The requirements include `opencv-python-headless` (used to clean scanned pages;
no model or training involved), `fonttools` (to subset the fonts embedded in each
translated page, which keeps the output PDF small) and `charset-normalizer` (to read
legacy-encoded TXT files).

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
python -m booktrans livre.pdf --target en       # French (detected) -> English
python -m booktrans book.pdf --target ja --output-mode target-only   # -> book_ja.pdf
```

Languages (`--source`, `--target`): English `en`, Simplified Chinese `zh-CN` (default target),
Traditional Chinese `zh-TW`, Japanese `ja`, Korean `ko`, Spanish `es`, French `fr`,
German `de`, Portuguese `pt`, Russian `ru`, Arabic `ar`, Hindi `hi`, Italian `it`. The list
lives in `booktrans/languages.py`.

| Option | Meaning |
| --- | --- |
| `-o, --output` | output PDF path |
| `--backend NAME` | LLM provider: `claude-cli` (default), `api`, `qwen`, `qwen-intl`, `deepseek`, `openai-compatible` |
| `--source LANG` | language of the book; default `auto` = detected from the text (several pages, so a cover in another language does not mislead). If detection is unsure the model identifies the language itself |
| `--target LANG` | language to translate into (default `zh-CN`) |
| `--output-mode MODE` | `bilingual` (default): each original page then its translation; `target-only`: translated pages only (a page with nothing to translate, such as a picture, is kept as it is). The default file name is `<book>_bilingual.pdf` or `<book>_<target>.pdf` |
| `--to FORMAT` | output format: `pdf`, `epub`, `docx` or `md` (default: from the `-o` file name, else `pdf`) |
| `--recommend` | print the settings suggested for the book, with reasons, and stop (nothing is spent) |
| `--model` | model name (default: the backend's default) |
| `--pages 1-20` | only this page range (a single number or `start-end`) |
| `--redo 9-10` | re-translate these pages even if cached |
| `--glossary FILE` | fixed renderings of names and terms, one `original=translation` per line (they override the automatic glossary) |
| `--no-auto-glossary` | do not build the automatic glossary of repeated names |
| `--max-spend YUAN` | stop and ask before spending more than this on the book in total, across runs (default 10; `0` = no limit; prices are estimates) |
| `--finish-partial` | spend nothing: write the output from the pages already translated |
| `--debug` | when something goes wrong, also print the technical details (they are always written to the log file) |
| `--flat` | PDF input: plain-text translated pages instead of the original layout |
| `--ocr` | OCR scanned pages (needs a vision-capable backend) |
| `--ocr-backend`, `--ocr-model` | use a different backend / model for OCR |
| `--export-glossary names.txt` | collect the book's names, write them to a text file for you to check, and stop (only the names are paid for) |
| `--apply-glossary` | translate again only the already-translated pages whose names you changed in the glossary |

Progress is cached in `<output>.cache.json`, so an interrupted run resumes
without re-paying for finished pages. Entries are keyed by target language (Simplified
Chinese keeps the plain keys of earlier versions), and the glossary is kept per target
(`<output>.glossary.<lang>.json`), so switching the target never reuses the wrong text.
With the default file names, running again with only `--output-mode` changed rebuilds
the PDF from the cache and spends nothing.

### Formats: any input to any output

```
python -m booktrans book.epub --to epub         # -> book_bilingual.epub, written into the original EPUB
python -m booktrans report.docx --to md         # Word in, Markdown out
python -m booktrans paper.pdf -o paper_zh.docx  # the format is taken from the file name
python -m booktrans book.pdf --recommend        # suggested settings and why; nothing is spent
```

| Input | Output | What is kept |
| --- | --- | --- |
| PDF | PDF | the page layout, as described under "Page layout" below |
| EPUB | EPUB | the book's own file: styles, pictures, fonts and contents page; each translated paragraph goes after its original (or replaces it with `--output-mode target-only`) |
| any other pair | PDF, EPUB, Word (`.docx`), Markdown | the text, pictures and tables in their original order, set in the target format's own way |

- A book that is not a PDF is read as **blocks** (`booktrans/blocks.py`): headings, paragraphs, list items,
  tables (cell by cell), pictures and code, in reading order. Code is not translated. Pictures are saved in
  `<output>.assets/`.
- Blocks are translated in units of about a page and cached under `B<n>` keys in `<output>.cache.json`, each
  with its **original text and its translation**. A unit whose text has changed is translated again; the others
  are not. Writing the same book in another format makes no model call.
- A PDF keeps its page-by-page cache (the `L<page>` keys), which serves every output format. Written as another
  format, its text blocks become headings (by type size) and paragraphs, its embedded pictures and drawn figures
  become pictures, and its ruled tables become tables.
- Markdown output puts its pictures in `<name>_assets/` next to the file. The web service and the desktop app
  give a `.zip` of both when there are pictures.
- Limits: EPUB or TXT written as **PDF** still goes through the older plain-text pages (no pictures or tables)
  and has its own cache entries, so that pair and the others do not share translations. Inline formatting
  (bold, links) inside a paragraph is not carried into the translation, except Markdown marks, which stay in
  the text. In a scanned PDF only the text is carried to other formats. Word text boxes, footnotes and comments
  are not read; legacy `.doc` is not supported. A figure in a PDF is found by its drawing, so a chart can be
  missed or cut wrongly; a table without ruling lines is written as paragraphs.

- Files that cannot be read stop at once with a message that says why: a PDF that needs a password (one that only
  restricts copying opens by itself; an AES-encrypted one needs the `cryptography` package), a damaged file, or a
  file of another kind saved under the wrong extension. `--to` and the extension of `-o` must agree
  (`-o book.docx --to md` is refused); a missing output folder is made, and one that cannot be written is
  reported before any page is paid for.
- A text file with no blank lines is read one paragraph per line (as most Chinese novels are), an indented line
  starts a paragraph, and a paragraph longer than a page is cut into pages, so a request never holds a whole book.

`--recommend` (and the upload step of the web and desktop pages) looks at the file and suggests settings, each
with a reason: the book's language, OCR for a scan, the output format, a first trial of 10 pages for a long
book, and checking the names first. It uses no model and costs nothing (`booktrans/recommend.py`).

### Check the names early, then fix the pages already translated

A name translated two ways, or wrongly, is easiest to catch before the whole book is paid for:

```
python -m booktrans book.pdf --export-glossary names.txt     # collects names, writes the file, stops
# edit names.txt: one `original=translation` per line, # starts a comment, a name left out is not fixed
python -m booktrans book.pdf --glossary names.txt            # translate with your names
```

Later, after reading the result, edit the file again and apply it to the pages already translated:

```
python -m booktrans book.pdf --glossary names.txt --apply-glossary
```

It says which pages mention a name whose rendering changed (or was added or removed), what
translating them again costs (a rough estimate), and asks before spending. Only those pages are
translated again and the PDF is rebuilt; every other page keeps its translation. The spend limit
applies. Each translated page remembers the glossary entries it was translated with
(`<output>.glossary-used.json`); a book translated by an older version has no such record, so
there every page that mentions a name in the glossary counts as possibly affected.

In the desktop app the names step has **Download names** and **Import edited file** (check the names
before the book is translated), and a finished book has **Review names**: edit a rendering or import a
file, **Apply to translated pages** shows the number of pages and the cost, and one more click
translates them again.

### Language detection and special characters

Detection (`languages.detect_language`) needs no model call or extra package: the writing
system settles Japanese (kana), Korean, Chinese (simplified or traditional), Russian, Arabic
and Hindi, and the commonest words settle English, Spanish, French, German, Portuguese and
Italian. The web pages show the detected language and let the user change it.

Text pages and redrawn pages are drawn with MuPDF's HTML engine and its built-in fonts, chosen
per character, so symbols (© ™ → • ½ ✓ …), accents, emoji and every listed script come from a
font that has them. Arabic is shaped and set right to left; Hindi conjuncts are shaped.
Control codes, U+FFFD and unassigned code points are removed before drawing, and legacy-encoded
TXT files (Shift-JIS, GBK, Big5, EUC-KR, Windows-1251/1252) are decoded properly. Limits: a
glyph that no built-in font has (some rare enclosed characters such as ㈠) is left blank, and
Japanese text shares the Chinese-oriented CJK font, so a few kanji use Chinese letter shapes.

### Page layout (text PDFs)

For PDFs with a text layer, the translated page is a copy of the original page with
its source text replaced in place, so headings, bullets, side panels and images
keep their positions. The text is translated block by block (cached under `L<page>`
keys in the cache file). Use `--flat` for plain-text translated pages.
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

What to do is a `booktrans.options.JobOptions`: the page range, the languages, the output mode,
the glossary options and so on, with their defaults and their checking in one place (a value that is not
allowed is a `ValueError` when it is made). `translate_book` takes one, or the same settings as keyword
arguments as above:

```python
from booktrans.options import JobOptions
translate_book("book.pdf", "out.pdf", translator, JobOptions(pages="1-20", target="fr"))
```

The command line and the web service each fill in one `JobOptions` and nothing else, so a new option
is added to `JobOptions` and `translate_book`, not to every entry point.

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

API: `GET /api/config` (includes `languages`, the list for the pickers, and `default_target`) →
`POST /api/jobs` (upload a `.pdf`, `.epub`, `.docx`, `.md` or `.txt`; the job carries `detected_language`,
`""` if unsure, and `recommended`: `{settings, reasons}` suggested for this book) →
`POST /api/jobs/{id}/start` (`api_key`, `pages`, `preview`, `ocr`, `source` (`auto` or a code),
`target` (default `zh-CN`), `output_mode` (`bilingual` or `target-only`), `output_format` (`pdf`, `epub`, `docx`, `md`); an unknown code is a 400) → `GET /api/jobs/{id}` (state, stage, done/total) →
`GET /api/jobs/{id}/download`; `DELETE /api/jobs/{id}` removes the files.
The glossary: `GET /api/jobs/{id}/glossary/download` (an editable `original=translation` text file),
`POST .../glossary/import` (`{"text": ...}`; a line that cannot be read is a 400 that names it and nothing is
saved), `GET .../glossary/changes` (how many translated pages the edits affect and the estimated cost; spends
nothing), then `POST .../start` with `"refresh_glossary": true` to translate just those pages again. All of them
answer 409 while the job runs.

### Deploying

`Dockerfile`, `docker-compose.yml` (app + Caddy for automatic HTTPS) and `.env.example`
run the web service on any Linux server. See [docs/DEPLOY.md](docs/DEPLOY.md) for a
step-by-step guide for Alibaba Cloud / Tencent Cloud (international sites, Singapore or
Tokyo region).

## Desktop app (building it)

The desktop app is the same engine behind a local window: `booktrans.desktop` opens a pywebview window and
starts the web service on `127.0.0.1` with a per-launch token; the API key is kept in the operating system's
credential store. The Windows installer is built by `.github/workflows/desktop-windows.yml` (tests, PyInstaller
build, smoke test, Inno Setup installer). That workflow keeps its installer as an Actions artifact for **14 days
only**, so downloads are published as GitHub Releases instead (see the Download section). To publish one:
download the installer from the workflow run, then `gh release create vX.Y.Z BookTranslator-Setup-X.Y.Z.exe`
and update the link, size and SHA-256 above.

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
  blocks.py       a book as blocks (headings, paragraphs, tables, pictures) and its units
  blockreaders.py EPUB / Word / Markdown / TXT -> blocks
  blockwriters.py blocks -> EPUB / Word / Markdown / PDF
  pdfblocks.py    a translated PDF -> blocks
  recommend.py    settings suggested for an uploaded book
  ocr.py          OCR of scanned pages (via a vision backend)
  translate.py    translation, retry/fallback, on-disk cache
  languages.py    the language list, page labels and language detection
  textclean.py    drops characters that cannot be drawn (U+FFFD, control codes...)
  layout.py       find text blocks / paragraphs / table cells on a PDF page, redraw it in the target language
  figures.py      clean ink layer of a scan (OpenCV): keeps lines, curves and symbols
  writer.py       assemble the PDF (bilingual or translation only); typeset text pages
  web/            web service: app.py (API), jobs.py (job storage, worker), static/index.html
  usage.py        token usage tracking
  spend.py        spend limit per book (counts every paid call, stops before going over)
  glossary.py     names glossary: collect, edit, apply to translated pages
  options.py      JobOptions: one validated definition of a job's settings
  failure.py      classified failure messages, log file, redacted keys (CLI, web and desktop)
  fsutil.py       small file helpers shared by the cache, glossary, OCR and spend files
  desktop/        desktop app shell (pywebview window; starts the web service on 127.0.0.1)
  prompts.py      prompts sent to the model
  backends/       LLMBackend interface + claude-cli, Anthropic api and OpenAI-compatible (Qwen, DeepSeek) providers
packaging/       Windows build: installer script (Inno Setup) and the installer's checks
tests/            pytest suite (uses a fake backend, no API calls)
```

## Tests

```
pip install -r requirements-dev.txt
python -m pytest tests
```

## License

GNU AGPL-3.0 (see `LICENSE`; the reason is PyMuPDF, see `docs/adr/0003-license-desktop-app-under-agpl.md`, and bundled
licenses are listed in `docs/THIRD_PARTY.md`). Earlier commits were published under MIT. This covers the code only; make
sure you have the right to translate any book you process.
