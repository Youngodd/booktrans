# Edge-case test plan (2026-11-15)

Baseline: 512 passed, 2 skipped. `tests/test_edge_cases.py` already covers the spend meter, glossary files,
text cleaning, TXT/PDF/EPUB corruption, page ranges, retry, cache damage, language detection, job store ids, CLI
option errors. This plan covers what is **not** covered yet, mostly the block pipeline added with the new
formats (EPUB / Word / Markdown in and out), plus a few older gaps. New tests go in
`tests/test_edge_formats.py`, `tests/test_edge_web.py` and `tests/test_edge_cli.py`. No model call is made: every
test uses the fake backends.

Each case is classified **pass**, **bug** (fixed in the source, test kept) or **limitation** (README lists it;
kept as `xfail`/asserting the documented behaviour). Highest risk first.

## 1. Safety of uploaded files (web service, so untrusted input)
- Markdown picture pointing outside the upload folder (`../x`, absolute path): must not be read into the output.
- Markdown picture that is not an image (a text file named `.png`): not embedded as a picture.
- EPUB with picture hrefs that climb out of the archive, EPUB with remote / `data:` pictures.
- Filenames: path separators, `..`, NUL, very long, only dots, unicode, Windows reserved names.
- Job ids with traversal; download of another job's file; double delete.

## 2. Corrupt, empty and odd input files (block readers)
- Empty `.docx` / `.md` / `.txt` / `.epub`; zero-byte files; whitespace only; text file saved as `.docx`.
- Truncated zip, a `.docx` that is an EPUB (and the reverse), password-protected PDF.
- Markdown: unclosed code fence, table with ragged rows / no header rule / escaped pipes, picture-only file,
  headings with only a picture, nested lists, CRLF and old-Mac CR line endings, BOM, front matter.
- Word: only a picture, only a table, nested table, merged cells, empty cells, heading style without text.
- A book with no translatable text (pictures only): a clear error, not an empty file.

## 3. Writers
- Every output format for text with `& < > " '`, control characters, U+FFFD, emoji, RTL, very long word,
  very long paragraph, 1-cell table, table with ragged rows, picture whose file is missing.
- A target-only book where the model answered `~` (keep) or an empty string.
- Output folder that does not exist / a file where a folder is expected / read-only folder.

## 4. Options, cache, resume (block pipeline)
- `--pages`: `0`, reversed, beyond the end, `5-`, `a-b`, negative, single unit; `--redo` outside the book.
- Backend fails mid-book (BackendError), then a second run pays only for the missing units.
- Corrupt / non-dict / list `.cache.json`; cache entry of the wrong length; text edited between runs.
- Switch target language, switch output format, switch bilingual to target-only: cache reuse.
- `only_cached` with partial cache for blocks; `refresh_glossary` with no glossary.
- Source equal to target; source `auto` on one-word text.

## 5. CLI
- `-o book.docx --to md` conflict; `-o` with unknown extension; `--to` with uppercase; `-o` into a missing folder;
  `--recommend` on every input type and on a corrupt file; book path with spaces / unicode.

## 6. Web service
- Unsupported / double / empty extension, empty file, oversize (413), corrupt file of each new type (400).
- `output_format` / `output_mode` / `source` / `target` invalid (400); `pages` malformed (400).
- Start twice (409), download before done (409), delete while running (409), unknown job (404).
- Several jobs at once; recommendation for every type; glossary endpoints while a job runs.

## 7. Recommendation
- Corrupt PDF, empty PDF, encrypted PDF, a Chinese book (target suggestion), a 1-page book, a 500-page book.

## Results (run 2026-11-15)

Suite: 512 passed before, **892 passed, 2 skipped** after (the 2 skips were already there: EPUB to PDF in `test_formats.py` is the plain-text path, tested elsewhere).
New files: `tests/test_edge_formats.py`, `test_edge_cli.py`, `test_edge_web.py`, `test_edge_more.py`,
`test_edge_desktop.py`. The `desktop` window check (`packaging/ui_check.py`) also passes.

### Bugs found and fixed
| # | Case | What went wrong | Fix |
| --- | --- | --- | --- |
| 1 | Markdown picture `![x](../secret)` or `/etc/hosts` in an uploaded book | the file was read and put into the output (any file of the machine, from the web service) | `blockreaders._own_picture`: only an image file inside the book's own folder |
| 2 | TXT with one paragraph per line (Chinese novels), or one huge paragraph, written as Word / EPUB / Markdown | the whole book became one block and one request (translation cut off at the answer limit), and spaces were put between Chinese lines | `read_text` reads line by line, joins wrapped lines without a space next to CJK, `split_long` cuts a paragraph into pages |
| 3 | EPUB paragraph with inline tags (`<b>`, drop caps, `<ruby>`, `<br>`) | a space at every tag: `italic .`, `T he story`, `你好 世界 。` | `readers.html_text` (one reader for every EPUB path) |
| 4 | Word table with a nested table | the nested table's text was dropped | cell text read from every paragraph in the cell |
| 5 | Damaged `.docx` / `.epub`, a text saved as `.docx`, a locked PDF | raw library exceptions (`PackageNotFoundError`, `EpubException`, `FileNotDecryptedError`); the web page said only "could not be read" | `UnreadableBook` (a `ValueError`) with the reason, shown by the web service and the command line |
| 6 | `-o out.docx --to md` | Markdown text written into a `.docx` file | refused; `--to MD` (case) and `.markdown` accepted |
| 7 | Output folder that does not exist or is read-only | `FileNotFoundError` after the model had been paid for | made, or refused before anything is paid for |
| 8 | Picture file missing when writing EPUB or Markdown | crash after the whole book was paid for | the picture is left out |
| 9 | Two runs on the same book at once | both wrote `cache.json.tmp`: `FileNotFoundError` | one temporary name per process and thread |
| 10 | `--pages " "` | "Invalid page range" | blank means all pages |
| 11 | `![b](<my pic.png>)` (name with a space) | not recognised as a picture | the `<...>` form is read |
| 12 | Desktop `prefs.json` holding `{"models": null}` or a list | `AttributeError` when the page asked for its saved models | read as nothing chosen |

### Documented limits (not changed)
- Markdown front matter (`---` block) is read as paragraphs and translated.
- Source language equal to the target still sends every page to the model (it works; it only wastes money).
- A blank scanned page whose OCR answer is empty is cached as empty and not read again unless `.ocr.json` is deleted.
- AES-encrypted PDFs need the `cryptography` package, which is not in `requirements.txt`; adding it changes the
  frozen build and `docs/THIRD_PARTY.md`, so it was left for a decision.
- An EPUB translated before the inline-tag fix has its cached passages read differently (no stray spaces), so
  those units are translated again once.

## Audit, three rounds (2026-11-15)

| Round | Bug | Fix |
| --- | --- | --- |
| 1 | An EPUB with a paragraph over a page long was written as a newly made EPUB (its own chapters and styles lost): the paragraph cutting added earlier broke the one-block-per-element match | EPUB paragraphs are not cut |
| 1 | A text file wrapped at 72 columns with no blank line became one paragraph per line | per-line paragraphs only when most lines end a sentence |
| 1 | `--help` and the log path failed where no home folder is known | falls back to the temp folder |
| 2 | `job.json` written through one fixed temporary name: two writers at once collided | one name per process and thread |
| 2 | Unused imports left by the error-handling change | removed |
| 3 | PDF written as Word / EPUB / Markdown read its text in drawing order: a title drawn last came last, columns could interleave | `pdfblocks.reading_order` (XY cut) |
| 3 | Markdown output turned a paragraph such as `1984. was a novel` or `# not a heading` into a list or heading | `blockwriters.md_paragraph` escapes line-start markers |

Known and left: the page count shown for an EPUB or text book is counted the old way, and a Word or Markdown
output uses units of about a page, so a page range chosen for one is a little different for the other.
