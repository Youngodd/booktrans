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


MIN_PAGE_CHARS = 20  # a page with less text than this is looked at again


class UnreadableBook(ValueError):
    """The file cannot be read as the kind of book its extension says: damaged, the wrong
    kind of file, or locked. The message says which, and is safe to show to the user."""


def open_pdf(path):
    """A pypdf reader for the PDF, or UnreadableBook with the reason (a file that needs a
    password to open, or whose encryption needs the `cryptography` package)."""
    from pypdf import PdfReader
    from pypdf.errors import DependencyError, FileNotDecryptedError, PdfReadError
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")  # most locked PDFs only restrict printing or copying: the empty password opens them
            len(reader.pages)
        return reader
    except FileNotDecryptedError as e:
        raise UnreadableBook("This PDF is protected by a password. Remove the password (open it in a PDF "
                             "viewer and save a copy without one) and try again.") from e
    except DependencyError as e:
        raise UnreadableBook("This PDF is encrypted and the `cryptography` package is needed to open it "
                             "(pip install cryptography).") from e
    except PdfReadError as e:
        raise UnreadableBook(f"This file is not a readable PDF ({e}).") from e


def read_pdf(path):
    """The text of each page. A page pypdf finds (almost) nothing on is read again with
    pymupdf: pypdf does not see text drawn inside a form (every page this program has redrawn
    is made that way), and such a page would pass for a scan and be left untranslated."""
    reader = open_pdf(path)
    pages = [reflow(page_text(p)) for p in reader.pages]
    short = [i for i, t in enumerate(pages) if len(t.strip()) < MIN_PAGE_CHARS]
    if short:
        try:
            import fitz
            with fitz.open(str(path)) as doc:
                for i in short:
                    text = reflow("\n\n".join(b[4] for b in doc[i].get_text("blocks") if b[6] == 0))
                    if len(text.strip()) > len(pages[i].strip()):
                        pages[i] = text
        except Exception as e:  # the second look is a help; pypdf's reading stands
            from . import failure
            failure.note("the second reading of short pages with pymupdf failed; pypdf's text is used", e)
    return pages


def page_text(page):
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except KeyError:  # a blank page has no /Contents
        return ""


_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5", "h6",
               "blockquote", "section", "article", "pre", "dd", "dt", "dl", "figure", "figcaption", "caption", "hr"}
_NO_TEXT_TAGS = {"script", "style", "head", "nav", "noscript", "template", "rt", "rp"}  # rt, rp: ruby readings


def html_text(el, skip=()):
    """The text of an HTML element as a reader sees it: no space is made at an inline tag
    (a drop cap `<span>T</span>he`, or `<b>word</b>.`, stays one word), a line or block break
    is a space, and a ruby reading is left out. Elements named in `skip` are left out too."""
    from bs4 import NavigableString, Tag
    out = []

    def walk(node):
        for ch in node.children:
            if isinstance(ch, NavigableString):
                if type(ch) is NavigableString:  # not a comment or a doctype
                    out.append(str(ch))
            elif isinstance(ch, Tag) and ch.name not in skip and ch.name not in _NO_TEXT_TAGS:
                if ch.name in _BLOCK_TAGS:
                    out.append(" ")
                walk(ch)
                if ch.name in _BLOCK_TAGS:
                    out.append(" ")
    walk(el)
    return " ".join("".join(out).split())


def read_epub(path):
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    book = epub.read_epub(str(path))
    paras = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for el in soup.find_all(["h1", "h2", "h3", "p"]):
            text = html_text(el)
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


def _pieces(text, limit):
    """`text` cut into pieces of at most `limit` characters, at line breaks, then sentence
    ends, then spaces, and only as a last resort in the middle of a word."""
    out = []
    while len(text) > limit:
        window = text[:limit + 1]
        cut = 0
        for pattern in (r"\n", r"[。！？…]+[”’」』)]*|[.!?][\"'”’)]*\s", r"\s"):
            found = [m.end() for m in re.finditer(pattern, window) if m.end() > limit // 4]
            if found:
                cut = found[-1]
                break
        cut = min(cut or limit, limit)
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        out.append(text)
    return [p for p in out if p]


def paginate(paras):
    """Group paragraphs into pages of about CHARS_PER_PAGE characters. A paragraph longer than
    a page (a text with one line break per line, or none) is cut so that no page is huge."""
    paras = [q for p in paras for q in _pieces(p, CHARS_PER_PAGE)]
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
    try:
        return readers[ext](path)
    except (UnreadableBook, OSError):
        raise
    except Exception as e:  # a damaged file, or one of another kind saved under this extension
        raise UnreadableBook(f"This file could not be read as a {ext} file ({type(e).__name__}: {str(e)[:120]}); "
                             "it may be damaged or of another kind.") from e


def parse_range(spec, total):
    spec = (spec or "").strip()
    if not spec:
        return list(range(total))
    a, sep, b = spec.partition("-")
    try:
        if sep and not b.strip():  # "5-" would silently mean page 5 only
            raise ValueError
        start, end = int(a), int(b or a)
    except ValueError:
        raise ValueError(f"Invalid page range {spec!r} (use e.g. 5 or 1-20)")
    if end < start:
        raise ValueError(f"Invalid page range {spec!r}: end is before start")
    return list(range(max(start, 1) - 1, min(end, total)))
