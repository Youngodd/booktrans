"""Write a book's blocks (see blocks.py) as EPUB, Word, Markdown or PDF.

Every writer takes the same blocks, already translated, and the assets folder with the
pictures. `bilingual` puts each original passage before its translation; otherwise only the
translation is written. An EPUB that came from an EPUB is written back into the original
file (write_epub_inplace), so its styles, pictures and contents page stay as they were.
"""
import io
import posixpath
import shutil
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from . import languages
from .blocks import cell_pairs, pairs
from .textclean import clean_text
from .writer import A4, MARGIN

MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
         "svg": "image/svg+xml", "webp": "image/webp", "bmp": "image/bmp"}
CSS = ("body {line-height: 1.5;} .tr {margin-top: 0.2em;} img {max-width: 100%;} "
       "table {border-collapse: collapse; margin: 0.8em 0;} "
       "td, th {border: 1px solid #888888; padding: 0.3em 0.5em; vertical-align: top;} "
       "pre {white-space: pre-wrap;}")


def _text(s):
    return escape(clean_text(s)).replace("\n", "<br/>")


def to_html(blocks, bilingual, src=lambda name: name, img_attrs=lambda name: ""):
    """The blocks as HTML body content. `src(name)` is the address of a picture."""
    out, open_list = [], None

    def close_list():
        nonlocal open_list
        if open_list:
            out.append("</%s>" % open_list)
            open_list = None

    for b in blocks:
        kind = b["type"]
        if kind != "list":
            close_list()
        if kind == "heading":
            tag = "h%d" % min(max(b.get("level", 2), 1), 6)
            out += ['<%s%s>%s</%s>' % (tag, ' class="tr"' if tr else "", _text(t), tag)
                    for t, tr in pairs(b, bilingual)]
        elif kind == "para":
            out += ['<p%s>%s</p>' % (' class="tr"' if tr else "", _text(t)) for t, tr in pairs(b, bilingual)]
        elif kind == "list":
            tag = "ol" if b.get("ordered") else "ul"
            if open_list != tag:
                close_list()
                out.append("<%s>" % tag)
                open_list = tag
            body = "<br/>".join(_text(t) for t, _ in pairs(b, bilingual))
            out.append('<li style="margin-left: %dem">%s</li>' % (b.get("level", 0) * 1.5, body))
        elif kind == "code":
            out.append("<pre>%s</pre>" % escape(clean_text(b["text"])))
        elif kind == "table":
            rows = []
            for r, row in enumerate(b["rows"]):
                cells = ["<td>%s</td>" % "<br/>".join(_text(t) for t, _ in cell_pairs(b, r, c, bilingual))
                         for c in range(len(row))]
                rows.append("<tr>%s</tr>" % "".join(cells))
            out.append("<table>%s</table>" % "".join(rows))
        elif kind == "figure":
            out.append('<p class="fig"><img src=%s alt=%s%s/></p>'
                       % (quoteattr(src(b["image"])), quoteattr(b.get("alt") or ""), img_attrs(b["image"])))
    close_list()
    return "\n".join(out)


def chapters(blocks):
    """The blocks cut into chapters: at the chapter boundaries, or else at the top headings."""
    out, cur = [], []
    marked = any(b["type"] == "break" for b in blocks)
    top = min([b.get("level", 1) for b in blocks if b["type"] == "heading"] or [1])
    for b in blocks:
        cut = b["type"] == "break" if marked else b["type"] == "heading" and b.get("level", 1) == top
        if cut and cur:
            out.append(cur)
            cur = []
        if b["type"] != "break":
            cur.append(b)
    if cur:
        out.append(cur)
    return out


def title_of(blocks, fallback):
    for b in blocks:
        if b["type"] == "heading":
            return b["text"]
    return fallback


# ---------------------------------------------------------------- EPUB

def write_epub(blocks, assets, out, *, bilingual=True, lang="zh-CN", title="Book"):
    """A new EPUB made from the blocks: one chapter file per chapter, pictures included."""
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("urn:uuid:" + str(uuid.uuid4()))
    book.set_title(title)
    book.set_language(lang)
    rtl = ' dir="rtl"' if languages.is_rtl(lang) and not bilingual else ""
    css = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(css)
    used = sorted({b["image"] for b in blocks if b["type"] == "figure"})
    for n, name in enumerate(used):
        ext = name.rsplit(".", 1)[-1].lower()
        book.add_item(epub.EpubItem(uid="img%d" % n, file_name="images/" + name,
                                    media_type=MEDIA.get(ext, "application/octet-stream"),
                                    content=(Path(assets) / name).read_bytes()))
    docs = []
    for n, chapter in enumerate(chapters(blocks) or [[{"type": "para", "text": ""}]], 1):
        doc = epub.EpubHtml(title=title_of(chapter, "%d" % n), file_name="chapter_%03d.xhtml" % n, lang=lang)
        doc.content = "<div%s>%s</div>" % (rtl, to_html(chapter, bilingual, lambda name: "images/" + name)
                                           or "<p></p>")
        doc.add_item(css)
        book.add_item(doc)
        docs.append(doc)
    book.toc = docs
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + docs
    epub.write_epub(str(out), book)


class NotTheSameBook(Exception):
    """The EPUB no longer reads as the blocks that were translated."""


def write_epub_inplace(source, blocks, assets, out, *, bilingual=True):
    """The original EPUB with the translation written into it: every other file of the book
    (styles, pictures, fonts, contents) is copied as it is.

    Each chapter is walked exactly as it was read, so the n-th block is the n-th element; a
    translated paragraph goes after its original (bilingual) or takes its place.
    """
    from bs4 import BeautifulSoup, NavigableString
    from ebooklib import epub
    from .blockreaders import epub_items, walk_html
    from .blocks import save_asset

    book = epub.read_epub(str(source))
    todo = iter([b for b in blocks if b["type"] != "break"])
    changed = {}
    with zipfile.ZipFile(str(source)) as zin:
        names = zin.namelist()

        def raw(file_name):
            """(entry name, bytes) of a chapter as it is stored: ebooklib's own copy of it has
            lost the <head>, and with it the link to the book's stylesheet."""
            hit = [n for n in names if n == file_name or n.endswith("/" + file_name)]
            if len(hit) != 1:
                raise NotTheSameBook(file_name)
            return hit[0], zin.read(hit[0])

        stored = {item.file_name: raw(item.file_name) for item in epub_items(book)}

    def put(soup, b, el):
        if b["type"] in ("code", "figure"):
            return
        if b["type"] == "table":
            for r, row in enumerate(el):
                for c, cell in enumerate(row):
                    shown = cell_pairs(b, r, c, bilingual)
                    if not shown[-1][1]:
                        continue
                    if bilingual:
                        cell.append(soup.new_tag("br"))
                        span = soup.new_tag("span", attrs={"class": "bt-tr"})
                        span.string = shown[-1][0]
                        cell.append(span)
                    else:
                        cell.clear()
                        cell.string = shown[-1][0]
            return
        shown = pairs(b, bilingual)
        if not shown[-1][1]:
            return  # nothing was translated: the original stays
        tr = clean_text(shown[-1][0])
        if isinstance(el, NavigableString):  # text straight inside a div
            if bilingual:
                span = soup.new_tag("span", attrs={"class": "bt-tr"})
                span.string = tr
                el.insert_after(span)
                el.insert_after(soup.new_tag("br"))
            else:
                el.replace_with(tr)
        elif b["type"] == "list":
            inner = el.find(["ul", "ol"], recursive=False)
            if bilingual:
                span = soup.new_tag("span", attrs={"class": "bt-tr"})
                span.string = tr
                for new in (soup.new_tag("br"), span):
                    inner.insert_before(new) if inner else el.append(new)
            else:
                for ch in list(el.children):
                    if getattr(ch, "name", None) not in ("ul", "ol", "table", "img"):
                        ch.extract()
                el.insert(0, tr)
        elif bilingual:
            new = soup.new_tag(el.name, attrs={k: v for k, v in el.attrs.items() if k != "id"})
            new["class"] = list(el.get("class") or []) + ["bt-tr"]
            new.string = tr
            el.insert_after(new)
        else:
            keep = el.find_all(["img", "image"])
            el.clear()
            for im in keep:
                el.append(im)
            el.append(tr)

    for item in epub_items(book):
        base = posixpath.dirname(item.file_name)

        def image(src, base=base):
            href = posixpath.normpath(posixpath.join(base, src.split("#")[0]))
            found = book.get_item_with_href(href)
            if found is None or src.startswith(("http:", "https:", "data:")):
                return None
            return save_asset(assets, found.get_content(), posixpath.splitext(href)[1])

        entry, data = stored[item.file_name]
        soup = BeautifulSoup(data, "html.parser")
        found = list(walk_html(soup.body or soup, image))
        for new, el in found:
            b = next(todo, None)
            same = b is not None and b["type"] == new["type"] and \
                (b.get("text"), b.get("rows")) == (new.get("text"), new.get("rows"))
            if not same:
                raise NotTheSameBook(item.file_name)
            put(soup, b, el)
        if found:
            changed[entry] = soup.decode(formatter="minimal").encode("utf-8")
    if next(todo, None) is not None:
        raise NotTheSameBook("blocks left over")

    with zipfile.ZipFile(str(source)) as zin, zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zout:
        by_entry = changed
        for info in sorted(zin.infolist(), key=lambda i: i.filename != "mimetype"):  # mimetype first
            data = by_entry.get(info.filename, None)
            data = zin.read(info.filename) if data is None else data
            stored = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            zout.writestr(info.filename, data, compress_type=stored)


# ---------------------------------------------------------------- Word

def write_docx(blocks, assets, out, *, bilingual=True, lang="zh-CN", title="Book"):
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, RGBColor
    doc = docx.Document()
    doc.core_properties.title = title
    rtl = languages.is_rtl(lang)
    width = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin

    def style(p, is_tr):
        if is_tr:
            for run in p.runs:
                run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
            if rtl:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    for b in blocks:
        kind = b["type"]
        if kind == "heading":
            for t, tr in pairs(b, bilingual):
                style(doc.add_heading(clean_text(t), level=min(max(b.get("level", 2), 1), 9)), tr)
        elif kind == "para":
            for t, tr in pairs(b, bilingual):
                style(doc.add_paragraph(clean_text(t)), tr)
        elif kind == "list":
            name = "List Number" if b.get("ordered") else "List Bullet"
            shown = pairs(b, bilingual)
            p = doc.add_paragraph(clean_text(shown[0][0]), style=name)
            for t, tr in shown[1:]:  # the translation on the next line of the same item
                run = p.add_run("\n" + clean_text(t))
                run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
        elif kind == "code":
            p = doc.add_paragraph()
            p.add_run(clean_text(b["text"])).font.name = "Courier New"
        elif kind == "table":
            cols = max(len(row) for row in b["rows"])
            table = doc.add_table(rows=len(b["rows"]), cols=cols)
            table.style = "Table Grid"
            for r, row in enumerate(b["rows"]):
                for c in range(len(row)):
                    table.cell(r, c).text = "\n".join(clean_text(t) for t, _ in cell_pairs(b, r, c, bilingual))
            doc.add_paragraph()
        elif kind == "figure":
            try:
                shape = doc.add_picture(str(Path(assets) / b["image"]))
                if shape.width > width:  # fit the page, keep the proportions
                    shape.height = int(shape.height * width / shape.width)
                    shape.width = width
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            except Exception:  # a picture format Word cannot hold (SVG, WebP): say so, go on
                doc.add_paragraph("[%s]" % (b.get("alt") or b["image"]))
        elif kind == "break":
            doc.add_page_break()
    doc.save(str(out))


# ---------------------------------------------------------------- Markdown

def assets_dir_of(out):
    """Where a Markdown file's pictures go: `<name>_assets/` next to it."""
    out = Path(out)
    return out.with_name(out.stem + "_assets")


def write_markdown(blocks, assets, out, *, bilingual=True, lang="zh-CN", title="Book"):
    """Markdown text; its pictures are copied to `<name>_assets/` next to the file."""
    out = Path(out)
    pictures = assets_dir_of(out)
    lines = []

    def cell(text):
        return clean_text(text).replace("|", "\\|").replace("\n", " ")

    for k, b in enumerate(blocks):
        kind = b["type"]
        if kind == "heading":
            for t, _ in pairs(b, bilingual):
                lines += ["#" * min(max(b.get("level", 2), 1), 6) + " " + clean_text(t).replace("\n", " "), ""]
        elif kind == "para":
            for t, _ in pairs(b, bilingual):
                lines += [clean_text(t), ""]
        elif kind == "list":
            mark = "1." if b.get("ordered") else "-"
            pad = "  " * b.get("level", 0)
            shown = [clean_text(t).replace("\n", " ") for t, _ in pairs(b, bilingual)]
            lines.append(pad + mark + " " + shown[0])
            lines += [pad + "  " + t for t in shown[1:]]
            if k + 1 == len(blocks) or blocks[k + 1]["type"] != "list":
                lines.append("")
        elif kind == "code":
            lines += ["```", clean_text(b["text"]), "```", ""]
        elif kind == "table":
            rows = [[" <br> ".join(cell(t) for t, _ in cell_pairs(b, r, c, bilingual))
                     for c in range(len(row))] for r, row in enumerate(b["rows"])]
            cols = max(len(r) for r in rows)
            rows = [r + [""] * (cols - len(r)) for r in rows]
            lines.append("| " + " | ".join(rows[0]) + " |")
            lines.append("|" + " --- |" * cols)
            lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            lines.append("")
        elif kind == "figure":
            pictures.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(assets) / b["image"], pictures / b["image"])
            lines += ["![%s](%s/%s)" % ((b.get("alt") or "").replace("]", ""), pictures.name, b["image"]), ""]
        elif kind == "break":
            lines += ["---", ""]
    out.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


# ---------------------------------------------------------------- PDF

def write_pdf(blocks, assets, out, *, bilingual=True, lang="zh-CN", title="Book", size=11):
    """A4 pages typeset from the blocks, with their pictures and tables."""
    import fitz
    rtl = languages.is_rtl(lang) and not bilingual
    box = fitz.Rect(0, 0, *A4) + (MARGIN, MARGIN, -MARGIN, -MARGIN)

    def img_attrs(name):
        try:
            with fitz.open(str(Path(assets) / name)) as im:
                w, h = im[0].rect.width, im[0].rect.height
        except Exception:
            return ""
        scale = min(1.0, box.width / w, box.height * 0.8 / h)
        return ' width="%d" height="%d"' % (w * scale, h * scale)

    html = to_html(blocks, bilingual, img_attrs=img_attrs) or "<p></p>"
    css = ("body {font-family: sans-serif; font-size: %.1fpt; line-height: 1.5; direction: %s; "
           "text-align: %s;} p {margin: 0 0 %.1fpt 0;} .tr {color: #1f3a5f;} "
           "td {border: 1px solid #888888; padding: 3pt;} pre {font-family: monospace; font-size: %.1fpt;}"
           % (size, "rtl" if rtl else "ltr", "right" if rtl else "left", size * 0.8, size * 0.85))
    archive = fitz.Archive(str(assets)) if Path(assets).is_dir() else None
    story = fitz.Story(html, user_css=css, archive=archive)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    more = True
    while more:
        dev = writer.begin_page(fitz.Rect(0, 0, *A4))
        more, _ = story.place(box)
        story.draw(dev)
        writer.end_page()
    writer.close()
    with fitz.open("pdf", buf.getvalue()) as doc:
        doc.subset_fonts()
        doc.set_metadata({"title": title})
        doc.save(str(out), garbage=4, deflate=True)


WRITERS = {"epub": write_epub, "docx": write_docx, "md": write_markdown, "pdf": write_pdf}


def write_blocks(blocks, assets, out, fmt, *, bilingual=True, lang="zh-CN", title="Book", source=None):
    """Write the translated blocks as `fmt`. An EPUB read from the EPUB `source` is written
    back into that file; if it no longer matches, a new EPUB is made instead."""
    if fmt == "epub" and source is not None and Path(source).suffix.lower() == ".epub":
        try:
            return write_epub_inplace(source, blocks, assets, out, bilingual=bilingual)
        except NotTheSameBook:
            pass
    WRITERS[fmt](blocks, assets, out, bilingual=bilingual, lang=lang, title=title)
