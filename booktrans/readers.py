"""Read a book into a list of page texts."""
import re
from pathlib import Path

CHARS_PER_PAGE = 1800  # for EPUB/TXT, which have no fixed pages


def reflow(text):
    """Rebuild paragraphs from layout-mode text.

    Blank lines separate blocks. Prose blocks (long lines) are joined into one
    paragraph; list/TOC-like blocks (short lines) keep one item per line.
    """
    paras, block = [], []

    def flush():
        if not block:
            return
        avg = sum(len(l) for l in block) / len(block)
        paras.append(" ".join(block) if avg > 50 else "\n".join(block))
        block.clear()

    for line in text.splitlines():
        line = re.sub(r"\s{2,}", " ", line.strip())
        if line:
            block.append(line)
        else:
            flush()
    flush()
    return "\n\n".join(paras)


def read_pdf(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return [reflow(page_text(p)) for p in reader.pages]


def page_text(page):
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except KeyError:  # a blank page has no /Contents
        return ""


def read_epub(path):
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    book = epub.read_epub(str(path))
    paras = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for el in soup.find_all(["h1", "h2", "h3", "p"]):
            text = el.get_text(" ", strip=True)
            if text:
                paras.append(text)
    return paginate(paras)


_LATIN_SINGLE_BYTE = {"cp1250", "cp1254", "cp1257", "cp775", "iso8859_2", "iso8859_4", "iso8859_9",
                      "iso8859_10", "iso8859_13", "iso8859_14", "iso8859_15", "iso8859_16",
                      "latin_1", "mac_roman", "mac_latin2", "cp850", "cp437"}


def decode_text(data):
    """Text of a file's bytes: UTF-8 or UTF-16 as they are, else the encoding that
    charset-normalizer finds (Shift-JIS, GBK, Big5, EUC-KR, Windows-1251...), so a legacy
    text file does not turn into mojibake. Undecodable bytes become U+FFFD only as a last
    resort (they are dropped again before drawing)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(data).best()
        if best is not None:
            if best.encoding in _LATIN_SINGLE_BYTE:  # western text: Windows-1252 is by far the likeliest
                try:
                    return data.decode("cp1252")
                except UnicodeDecodeError:
                    pass
            return str(best)
    except ImportError:
        pass
    return data.decode("cp1252", errors="replace")


def read_txt(path):
    text = decode_text(Path(path).read_bytes())
    return paginate([p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()])


def paginate(paras):
    pages, cur, size = [], [], 0
    for p in paras:
        if cur and size + len(p) > CHARS_PER_PAGE:
            pages.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(p)
        size += len(p)
    if cur:
        pages.append("\n\n".join(cur))
    return pages


def read_book(path):
    ext = Path(path).suffix.lower()
    readers = {".pdf": read_pdf, ".epub": read_epub, ".txt": read_txt}
    if ext not in readers:
        raise ValueError(f"Unsupported file type: {ext} (use .pdf, .epub or .txt)")
    return readers[ext](path)


def parse_range(spec, total):
    if not spec:
        return list(range(total))
    a, _, b = spec.partition("-")
    try:
        start, end = int(a), int(b or a)
    except ValueError:
        raise ValueError(f"Invalid page range {spec!r} (use e.g. 5 or 1-20)")
    if end < start:
        raise ValueError(f"Invalid page range {spec!r}: end is before start")
    return list(range(max(start, 1) - 1, min(end, total)))
