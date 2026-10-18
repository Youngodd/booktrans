"""OCR for scanned PDF pages, using a vision-capable backend."""
import json
import sys

from .prompts import OCR_PROMPT
from .translate import load_cache

OCR_DPI = 150


def ocr_page(backend, path, i):
    """Transcribe page i of a scanned PDF."""
    import fitz  # pymupdf
    with fitz.open(str(path)) as doc:
        img = doc[i].get_pixmap(dpi=OCR_DPI).tobytes("jpeg")
    return backend.ocr_image(img, OCR_PROMPT)


def ocr_scanned_pages(backend, book, idx, pages, scanned, cache_path, progress=None):
    """Fill pages[n] with OCR text for each scanned n; cached and resumable."""
    cache = load_cache(cache_path)
    for k, n in enumerate(scanned, 1):
        key = str(idx[n])
        if key not in cache:
            print(f"OCR page {idx[n] + 1} ({k}/{len(scanned)})...", flush=True)
            cache[key] = ocr_page(backend, book, idx[n])
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        pages[n] = cache[key]
        if progress:
            progress("ocr", k, len(scanned))
