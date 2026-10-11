# book-translator

Translate English books (PDF / EPUB / TXT) into a bilingual PDF: each English
page is followed by its Chinese translation on the next page.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Use

```
python booktrans.py mybook.epub                 # -> mybook_bilingual.pdf
python booktrans.py mybook.pdf --pages 1-10     # -> mybook_bilingual pages 1-10.pdf
```

Progress is cached in `<output>.cache.json`, so an interrupted run resumes
without re-paying for finished pages.

### Page layout (text PDFs)

For PDFs with a text layer, the Chinese page is a copy of the original page with
its English text replaced in place, so headings, bullets, side panels and images
keep their positions. The text is translated block by block (cached under `L<page>`
keys in the cache file). Use `--flat` for the older plain-text Chinese pages.
Scanned pages (`--ocr`), EPUB and TXT always use plain-text pages. Known limits:
inline highlights such as a boxed word, and dashed link underlines, stay in place
without their text.

### Scanned PDFs

Pages with no text layer are detected automatically. To read them with
Claude's vision, add `--ocr`. It works with both backends: the default
`claude-cli` uses your Claude subscription login (no API key needed), and
`--backend api` uses the API.

```
python booktrans.py scan.pdf --ocr --pages 1-5   # test first
```

OCR text is cached in `<output>.ocr.json` and is checked for each page, so
re-runs don't pay for images again. Vision OCR can occasionally misread a poor
scan, so spot-check a few pages. Use `--ocr-model` to pick a different model
for OCR than for translation.

## License

MIT. This covers the code only; make sure you have the right to translate any book you process.
