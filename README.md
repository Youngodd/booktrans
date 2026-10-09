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
python booktrans.py mybook.pdf --pages 1-10     # try a sample first
```

Progress is cached in `<output>.cache.json`, so an interrupted run resumes
without re-paying for finished pages.

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
