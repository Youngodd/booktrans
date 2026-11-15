"""Read a book into blocks (see blocks.py): EPUB, Word (.docx), Markdown and plain text.

Pictures are saved in the assets folder and tables keep their rows and cells, so a writer can
put them back in any format. PDF pages become blocks in pipeline.py, from the page layout.
"""
import posixpath
import re
from pathlib import Path

from .blocks import save_asset
from .readers import CHARS_PER_PAGE, UnreadableBook, _pieces, decode_text, html_text

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_SKIP = {"script", "style", "head", "nav", "noscript", "template"}
_INLINE_BREAK = re.compile(r"\s+")


def _cjk(ch):
    return "\u2e80" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff" or "\uff00" <= ch <= "\uffef"


def join_lines(lines):
    """Lines of one paragraph as one string: a space between words, none next to Chinese,
    Japanese or Korean text (which is not written with spaces)."""
    out = ""
    for line in lines:
        line = line.strip()
        if line:
            out += (" " if out and not (_cjk(out[-1]) or _cjk(line[0])) else "") + line
    return out


def _clean(text):
    return _INLINE_BREAK.sub(" ", text or "").strip()


# ---------------------------------------------------------------- HTML (EPUB chapters)

def walk_html(root, image):
    """The blocks of an HTML element, in order, each with the element it came from:
    yields (block, element). `image(src)` stores a picture and returns its asset name or None.

    The same walk is used to read an EPUB and to write the translation back into it, so the
    n-th block always belongs to the same element.
    """
    from bs4 import NavigableString, Tag

    def figure(el):
        src = el.get("src") or el.get("xlink:href") or el.get("href")
        name = image(src) if src else None
        if name:
            yield {"type": "figure", "image": name, "alt": _clean(el.get("alt") or "")}, el

    def own_text(el):
        """Text of `el` without its nested lists and tables (they are blocks of their own)."""
        return html_text(el, skip=("ul", "ol", "table"))

    def walk(el, depth):
        for ch in list(el.children):
            if isinstance(ch, NavigableString):
                text = _clean(str(ch))
                if text and type(ch) is NavigableString:  # not a comment or a doctype
                    yield {"type": "para", "text": text}, ch
                continue
            if not isinstance(ch, Tag) or ch.name in _SKIP:
                continue
            name = ch.name
            if name in HEADINGS:
                text = html_text(ch)
                if text:
                    yield {"type": "heading", "text": text, "level": HEADINGS[name]}, ch
                for im in ch.find_all(["img", "image"]):
                    yield from figure(im)
            elif name in ("p", "figcaption", "dt", "dd", "caption"):
                for im in ch.find_all(["img", "image"]):
                    yield from figure(im)
                text = html_text(ch)
                if text:
                    yield {"type": "para", "text": text}, ch
            elif name in ("img", "image"):
                yield from figure(ch)
            elif name == "pre":
                text = ch.get_text().strip("\n")
                if text.strip():
                    yield {"type": "code", "text": text}, ch
            elif name in ("ul", "ol"):
                for li in ch.find_all("li", recursive=False):
                    for im in li.find_all(["img", "image"]):
                        yield from figure(im)
                    text = own_text(li)
                    if text:
                        yield {"type": "list", "text": text, "level": depth,
                               "ordered": name == "ol"}, li
                    for sub in li.find_all(["ul", "ol"], recursive=False):
                        yield from walk(_wrap(sub), depth + 1)
            elif name == "table":
                cells = [[c for c in tr.find_all(["th", "td"])] for tr in ch.find_all("tr")]
                cells = [row for row in cells if row]
                if cells:
                    yield {"type": "table", "rows": [[html_text(c) for c in row]
                                                     for row in cells]}, cells
            else:  # div, section, body, blockquote, figure, span, a ...: look inside
                yield from walk(ch, depth)

    def _wrap(el):
        """An element whose only child is `el`, so walk() meets `el` itself."""
        class One:
            children = [el]
        return One

    yield from walk(root, 0)


def epub_items(book):
    """The chapters of an EPUB in reading order (the spine), without the navigation page."""
    import ebooklib
    items = []
    for ref in book.spine:
        item = book.get_item_with_id(ref[0] if isinstance(ref, (tuple, list)) else ref)
        if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
            items.append(item)
    if not items:
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    return [it for it in items if "nav" not in (getattr(it, "properties", None) or [])]


def read_epub(path, assets):
    from ebooklib import epub
    from bs4 import BeautifulSoup
    book = epub.read_epub(str(path))
    blocks = []
    for item in epub_items(book):
        base = posixpath.dirname(item.file_name)

        def image(src, base=base):
            href = posixpath.normpath(posixpath.join(base, src.split("#")[0]))
            found = book.get_item_with_href(href)
            if found is None or src.startswith(("http:", "https:", "data:")):
                return None
            return save_asset(assets, found.get_content(), posixpath.splitext(href)[1])

        soup = BeautifulSoup(item.get_content(), "html.parser")
        found = [b for b, _ in walk_html(soup.body or soup, image)]
        if found:
            if blocks:
                blocks.append({"type": "break"})
            blocks.extend(found)
    return blocks


# ---------------------------------------------------------------- Word

def read_docx(path, assets):
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = docx.Document(str(path))
    blocks = []

    def pictures(p):
        for blip in p._p.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            part = doc.part.related_parts.get(rid) if rid else None
            if part is not None:
                ext = Path(str(part.partname)).suffix or "." + part.content_type.split("/")[-1]
                blocks.append({"type": "figure", "image": save_asset(assets, part.blob, ext), "alt": ""})

    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, doc)
            pictures(p)
            text = _clean(p.text)
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"(?i)heading (\d)", style)
            if m or style.lower() in ("title", "subtitle"):
                blocks.append({"type": "heading", "text": text, "level": int(m.group(1)) if m else 1})
            elif style.lower().startswith("list") or child.find(".//" + qn("w:numPr")) is not None:
                blocks.append({"type": "list", "text": text, "level": 0,
                               "ordered": "number" in style.lower()})
            else:
                blocks.append({"type": "para", "text": text})
        elif child.tag == qn("w:tbl"):
            rows = []
            for row in Table(child, doc).rows:
                cells, seen = [], set()
                for cell in row.cells:  # a merged cell is listed once per column it spans
                    if id(cell._tc) not in seen:
                        seen.add(id(cell._tc))
                        cells.append(_clean(" ".join(Paragraph(p, doc).text for p in cell._tc.iter(qn("w:p")))))
                rows.append(cells)
            if any(any(row) for row in rows):
                blocks.append({"type": "table", "rows": rows})
    return blocks


# ---------------------------------------------------------------- Markdown

_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^)\s>]+))(?:\s+\"[^\"]*\")?\s*\)")
_MD_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_MD_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _md_row(line):
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") and not line.endswith("\\|") else line
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}


def _own_picture(folder, src):
    """The picture file a Markdown mark points to, if it is an image inside the book's own
    folder; None for a web address, a missing file, a file of another kind, or a path that
    leaves the folder (an uploaded book must not pull in other files of the machine)."""
    from urllib.parse import unquote
    if re.match(r"(?i)^[a-z][a-z0-9+.-]*:", src) or src.startswith(("/", "\\")):
        return None
    try:
        root = Path(folder).resolve()
        file = (root / unquote(src.split("#")[0].split("?")[0])).resolve()
        file.relative_to(root)
    except (ValueError, OSError):
        return None
    return file if file.suffix.lower() in IMAGE_TYPES and file.is_file() else None


def read_markdown(path, assets):
    """Markdown as blocks. Inline marks (**bold**, links) stay in the text as they are."""
    path = Path(path)
    lines = decode_text(path.read_bytes()).splitlines()
    blocks, para, k = [], [], 0

    def flush():
        if para:
            blocks.append({"type": "para", "text": join_lines(para)})
            para.clear()

    def images(line):
        """Take the pictures out of a line; returns what is left of it."""
        def one(m):
            alt, src = m.group(1), m.group(2) or m.group(3)
            file = _own_picture(path.parent, src)
            if file is not None:
                flush()
                blocks.append({"type": "figure", "alt": alt,
                               "image": save_asset(assets, file.read_bytes(), file.suffix)})
                return ""
            return m.group(0)  # a picture on the web, or a missing file: the mark stays as text
        return _MD_IMAGE.sub(one, line)

    while k < len(lines):
        line = lines[k]
        if re.match(r"^\s*(```|~~~)", line):
            flush()
            fence = line.strip()[:3]
            body = []
            k += 1
            while k < len(lines) and not lines[k].strip().startswith(fence):
                body.append(lines[k])
                k += 1
            if "\n".join(body).strip():
                blocks.append({"type": "code", "text": "\n".join(body)})
            k += 1
            continue
        if "|" in line and k + 1 < len(lines) and _MD_RULE.match(lines[k + 1]) and "-" in lines[k + 1]:
            flush()
            rows = [_md_row(line)]
            k += 2
            while k < len(lines) and "|" in lines[k] and lines[k].strip():
                rows.append(_md_row(lines[k]))
                k += 1
            width = max(len(r) for r in rows)
            blocks.append({"type": "table", "rows": [r + [""] * (width - len(r)) for r in rows]})
            continue
        k += 1
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            flush()
            text = images(m.group(2)).strip()
            if text:
                blocks.append({"type": "heading", "text": text, "level": len(m.group(1))})
            continue
        if not line.strip() or re.match(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", line):
            flush()
            continue
        m = _MD_LIST.match(line)
        if m:
            flush()
            text = images(m.group(3)).strip()
            if text:
                blocks.append({"type": "list", "text": text, "level": len(m.group(1)) // 2,
                               "ordered": m.group(2)[0].isdigit()})
            continue
        rest = images(re.sub(r"^\s*>\s?", "", line)).strip()
        if rest:
            para.append(rest)
    flush()
    return blocks


SENTENCE_END = ".!?…。！？”’」』\"')）】》"


def read_text(path, assets=None):
    """Plain text as paragraphs. Blank lines separate them; a file with none (one paragraph per
    line, as most Chinese novels are) is read line by line, and an indented line starts a new
    paragraph. Lines hard-wrapped inside a paragraph are joined."""
    text = decode_text(Path(path).read_bytes())
    chunks = [c for c in re.split(r"\n\s*\n", text) if c.strip()]
    if len(chunks) == 1:
        lines = [c for c in chunks[0].splitlines() if c.strip()]
        ended = sum(1 for l in lines if l.rstrip()[-1] in SENTENCE_END)
        if len(lines) > 1 and ended >= 0.6 * len(lines):  # most lines end a sentence: one paragraph per line
            chunks = lines                                  # (lines that stop mid-sentence are one wrapped paragraph)
    out = []
    for chunk in chunks:
        lines = [[]]
        for line in chunk.splitlines():
            if line.strip():
                if lines[-1] and re.match(r"^(\u3000|\t| {2,})", line):  # an indented line begins a paragraph
                    lines.append([])
                lines[-1].append(line)
        out += [{"type": "para", "text": " ".join(join_lines(l).split())} for l in lines if l]
    return out


def split_long(blocks):
    """A paragraph longer than a page is cut (at line ends, then sentence ends) into paragraphs
    of a page: it would otherwise go to the model in one request, and its translation would be
    cut off at the model's answer limit."""
    out = []
    for b in blocks:
        if b["type"] == "para" and len(b["text"]) > CHARS_PER_PAGE:
            out += [{"type": "para", "text": piece} for piece in _pieces(b["text"], CHARS_PER_PAGE)]
        else:
            out.append(b)
    return out


READERS = {".epub": read_epub, ".docx": read_docx, ".md": read_markdown, ".markdown": read_markdown,
           ".txt": read_text}


def read_blocks(path, assets):
    """The blocks of a book; its pictures are saved in the `assets` folder."""
    ext = Path(path).suffix.lower()
    if ext not in READERS:
        raise ValueError(f"Unsupported file type: {ext}")
    try:
        found = READERS[ext](path, assets)
        # not an EPUB: its blocks must stay one per element, so the translation can be written back into the book itself
        return found if ext == ".epub" else split_long(found)
    except (UnreadableBook, OSError):
        raise
    except Exception as e:  # a damaged file, or one of another kind saved under this extension
        raise UnreadableBook(f"This file could not be read as a {ext} file ({type(e).__name__}: {str(e)[:120]}); "
                             "it may be damaged or of another kind.") from e
