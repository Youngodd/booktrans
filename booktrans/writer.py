"""Assemble the output PDF: the original pages and/or the translated pages.

Text pages (EPUB, TXT, flat PDF) are typeset with the same engine that redraws a PDF page
in place (pymupdf's HTML box). It shapes Arabic and Hindi, runs right-to-left text, and
picks a font for every character from its built-in set, so a symbol or a script the main
font lacks is drawn from another font instead of coming out as a wrong glyph or nothing.
"""
import io
from xml.sax.saxutils import escape

from . import languages
from .textclean import clean_text

MARGIN = 20 / 25.4 * 72  # 20 mm in points
A4 = (595.28, 841.89)


def _html(text, label, rtl):
    paras = [p for p in clean_text(text).split("\n\n")] or [""]
    body = "".join("<p>%s</p>" % escape(p).replace("\n", "<br>") for p in paras)
    return '<p class="label">%s</p>%s' % (escape(clean_text(label)), body)


def _css(size, rtl, serif):
    return ("body {font-family: %s; font-size: %.1fpt; line-height: 1.5; direction: %s; "
            "text-align: %s;} p {margin: 0 0 %.1fpt 0;} "
            ".label {font-size: 8pt; color: #888888; margin-bottom: 12pt;}"
            % ("serif" if serif else "sans-serif", size, "rtl" if rtl else "ltr",
               "right" if rtl else "left", size * 0.9))


def text_pages(text, label, lang, serif=False, lo=10, hi=15):
    """PDF bytes of `text` on A4 page(s): the largest size in [lo, hi] that fits one page,
    else `lo` with the text flowing onto further pages."""
    import fitz
    rtl = languages.is_rtl(lang)
    html = _html(text, label, rtl)
    media = fitz.Rect(0, 0, *A4)
    where = media + (MARGIN, MARGIN, -MARGIN, -MARGIN)
    size = lo
    for s in range(hi * 2, lo * 2 - 1, -1):
        if not fitz.Story(html, user_css=_css(s / 2, rtl, serif)).place(where)[0]:
            size = s / 2
            break
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    story = fitz.Story(html, user_css=_css(size, rtl, serif))
    more = True
    while more:
        dev = writer.begin_page(media)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    with fitz.open("pdf", buf.getvalue()) as doc:
        doc.subset_fonts()  # the fallback fonts are large; keep only the glyphs used
        return doc.tobytes(garbage=4, deflate=True)


def make_pdf(pages, translations, out_path, original_pdf=None, zh_pages=None, *,
             source="en", target=languages.DEFAULT_TARGET, mode="bilingual"):
    """Write the PDF.

    pages          source text of each page (used when the original layout is not copied)
    translations   flat translation of each page ("" for pages redrawn in place)
    original_pdf   the source PDF whose pages are copied, if any
    zh_pages       {page position: PDF bytes of the redrawn page} for in-place layout
    mode           "bilingual": every original page, then its translation;
                   "target-only": only the translation (a page with nothing to translate,
                   such as a picture or the cover, is copied from the original)
    """
    from pypdf import PdfReader, PdfWriter

    bilingual = mode == "bilingual"
    src = PdfReader(str(original_pdf)) if original_pdf else None
    writer = PdfWriter()

    def add(data):
        for p in PdfReader(io.BytesIO(data)).pages:
            writer.add_page(p)

    src_name = languages.native_name(source)
    tgt_name = languages.native_name(target)
    for i, text in enumerate(pages):
        if bilingual:
            if src:
                writer.add_page(src.pages[i])
            else:
                add(text_pages(text, f"{src_name} — {languages.page_label(source, i + 1)}",
                               source, serif=True))
        if zh_pages and i in zh_pages:
            add(zh_pages[i])
            continue
        if not translations[i]:
            if bilingual and i == 0:
                # Viewers show the cover alone; no filler page, so later
                # original/translation pairs line up as two-page spreads.
                continue
            if not bilingual and src:  # nothing to translate here: keep the page as it is
                writer.add_page(src.pages[i])
                continue
        add(text_pages(translations[i] or "—",
                       f"{tgt_name} — {languages.page_label(target, i + 1)}", target))
    with open(out_path, "wb") as f:
        writer.write(f)
