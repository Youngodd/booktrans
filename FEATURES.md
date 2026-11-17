# Book Translator — Feature list (recent additions)

Source: `git log` since 2026-11-09 (HEAD `5c20692`, 2026-11-15). Each item is taken from a commit message, with the area of code it touches. Nothing here was checked by running the app; the test status is in the last section.

## Formats
- **Any input, any output** — EPUB, Word, Markdown and TXT are read as blocks (headings, paragraphs, lists, tables, pictures, code). Output can be PDF, EPUB, Word or Markdown. Files: `booktrans/` readers and writers, `--to`, `output_format` in the web API. (`fddc6e3`)
- **Re-export without a model call** — Blocks are cached under `B<n>` keys, so a translated book can be written in another format for free. An EPUB written as EPUB goes back into the original file. (`fddc6e3`)
- **Settings suggestion** — `--recommend` and the upload step of the pages suggest settings for the book, with reasons, using no model. (`fddc6e3`)
- **Word support** — adds the python-docx and lxml dependencies. (`fddc6e3`)

## Glossary
- **Export, import and apply edits** — Each page records the glossary entries it used, so after an edit only the pages that mention a changed, added or removed name are translated again. CLI: `--export-glossary`, `--apply-glossary`. Web API: `glossary/download`, `glossary/import`, `glossary/changes`, `refresh_glossary`. Desktop: Download/Import names, Review names, Apply to translated pages, with page count and cost. (`616445a`)

## PDF layout
- **Word spaces kept** — Blank spans count as a space, so "HongKong" no longer happens with browser-printed PDFs. (`85f0d46`)
- **Table cells stay separate** — Cells that share a row are no longer joined into one block. (`b754a2d`)
- **Wrapped lines joined** — A line stored as its own block is joined to the block above when it is that block's wrapped rest. (`e7a3b65`)
- **One text size per style** — Every page is measured first, and a style gets one size that fits all but a tenth of the pages. (`e7a3b65`)
- **PDF text in reading order** — (`b88d02e`)

## Providers
- **DeepSeek thinking off** — Calls send `thinking: disabled`, and an answer cut off before it began says why. (`7b64ca0`)
- **Qwen** — Versioned model ids (qwen3.7-plus, qwen3.8-max, qwen3.8-flash), thinking off, prices updated. (`b88d02e`)

## Desktop and web UI
- **Run summary** — While a book runs, the progress card shows the book (name, pages, range or preview) and how it is translated (languages, output mode, provider, model). The key is never shown. (`8603fe1`)
- **Settings form restored** — Filled from the saved job when a job reopens, pauses or fails. (`8603fe1`)
- **Select heights** — Language, format and output pickers match the model pickers on macOS. (`b88d02e`)
- **App icon** — Icon for the exe and installer, plus a page favicon and header logo. (`3ba1acd`)

## Reliability and security
- **Failure reporting** — New `booktrans/failure.py`, shared by CLI, web and desktop. It gives a classified message with task, backend and model, retry notices, the provider's reason, redacted keys, a log file and `--debug`. The CLI never ends in a bare traceback. (`b88d02e`)
- **Markdown picture sandbox** — An uploaded Markdown book can no longer pull in files outside its own folder. (`b88d02e`)
- **Reader fixes** — One paragraph per line, huge paragraphs, inline EPUB tags, nested Word tables, damaged files with a reason, locked PDFs, missing output folders, missing picture at write time. (`b88d02e`)
- **Markdown output escaping** — Paragraph text that would read as a list, heading or quote is escaped. (`b88d02e`)
- **CLI checks** — `-o` extension and `--to` must agree, and `--to` is case-insensitive. (`b88d02e`)
- **Race fixes** — Cache and job files use one temporary name per process and thread. Writers of a job's state file take turns, and the read is retried, for Windows. (`b88d02e`, `5c20692`)
- **Finishing without spending** — A page that no longer matches its blocks is left out instead of failing the run. (`dc09981`)

## Internal
- **`JobOptions`** — One validated definition of a job's settings, shared by the CLI, web runner and pipeline. (`7375d2f`)
- **Import cycle removed** — `complete()` and `RETRY_DELAYS` moved to `backends.base`. `tests/test_architecture.py` fails on a cycle or a lower layer importing a higher one. (`32ead65`)
- **About 440 edge-case tests** — See `docs/edge-case-test-plan.md`. (`b88d02e`)

## Test run
- Latest download: `~/Downloads/BookTranslator-Setup (3).zip` (2026-11-16). It holds only `BookTranslator-Setup-0.1.33.exe`, a Windows installer with no source or tests, so unit tests cannot run against it. They were run on the repo HEAD, the nearest source (the zip is dated a day after the last commit).
- Command: `.venv/bin/python -m pytest tests -q --ignore=tests/e2e`
- Result: **955 passed, 2 skipped, 0 failed** (about 24 s).
- Not run: `tests/e2e`, and the installer's own checks in `packaging/` (Windows only).
- Coverage: each area above has tests (`test_formats`, `test_readers`, `test_recommend`, `test_glossary_apply`, `test_layout_spaces`, `test_table_layout`, `test_run_summary`, `test_failure`, `test_job_options`, `test_architecture`, `test_edge_*`). The Qwen and DeepSeek request changes were not checked individually. The macOS select heights and the app icon have no unit tests (unverified).
