"""Assemble the bilingual PDF."""
import io
import re
from xml.sax.saxutils import escape


def make_pdf(pages, translations, out_path, original_pdf=None, zh_pages=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from pypdf import PdfReader, PdfWriter

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    margin = 20 * mm
    frame_w, frame_h = A4[0] - 2 * margin, A4[1] - 2 * margin

    def make_style(name, font, size, leading_ratio):
        return ParagraphStyle(name, fontName=font, fontSize=size,
                              leading=size * leading_ratio, spaceAfter=size * 0.9,
                              wordWrap="CJK" if font == "STSong-Light" else None)

    ascii_run = re.compile(r"[\x21-\x7e](?:[\x20-\x7e]*[\x21-\x7e])?")
    cjk = re.compile(r"[\u3400-\u9fff]")

    def mixed(line):
        # Latin/digit runs get a real Latin font plus a thin gap against
        # adjacent Chinese characters (STSong's built-in Latin is cramped).
        out, pos = [], 0
        for m in ascii_run.finditer(line):
            out.append(escape(line[pos:m.start()]))
            pad_l = " " if m.start() and cjk.match(line[m.start() - 1]) else ""
            pad_r = " " if m.end() < len(line) and cjk.match(line[m.end()]) else ""
            out.append(f"<font name='Times-Roman'>{pad_l}{escape(m.group())}{pad_r}</font>")
            pos = m.end()
        out.append(escape(line[pos:]))
        return "".join(out)

    def build_flow(text, font, size, ratio, label):
        style = make_style("body", font, size, ratio)
        head = ParagraphStyle("head", parent=style, fontSize=8, leading=10)
        flow = [Paragraph(f"<font color='#888888'>{label}</font>", head),
                Spacer(1, 4 * mm)]
        for para in text.split("\n\n") or [""]:
            body = ("<br/>".join(mixed(l) for l in para.split("\n"))
                    if font == "STSong-Light" else escape(para).replace("\n", "<br/>"))
            flow.append(Paragraph(body, style))
        return flow

    def fits(flow):
        total = 0
        for f in flow:
            _, h = f.wrap(frame_w, frame_h)
            total += h + f.getSpaceAfter()
        return total <= frame_h

    def render(text, font, ratio, label, lo=10, hi=15):
        # largest font size in [lo, hi] that still fits on one page; longer
        # text is left at `lo` and flows onto extra pages
        size = lo
        for s in range(hi * 2, lo * 2 - 1, -1):
            if fits(build_flow(text, font, s / 2, ratio, label)):
                size = s / 2
                break
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=margin,
                                rightMargin=margin, topMargin=margin,
                                bottomMargin=margin)
        doc.build(build_flow(text, font, size, ratio, label))
        return PdfReader(io.BytesIO(buf.getvalue()))

    src = PdfReader(str(original_pdf)) if original_pdf else None
    writer = PdfWriter()
    for i, text in enumerate(pages):
        if src:
            writer.add_page(src.pages[i])
        else:
            for p in render(text, "Times-Roman", 1.4, f"English — page {i + 1}").pages:
                writer.add_page(p)
        if zh_pages and i in zh_pages:
            for p in PdfReader(io.BytesIO(zh_pages[i])).pages:
                writer.add_page(p)
            continue
        if i == 0 and not translations[i]:
            # Viewers show the cover alone; no filler page, so later
            # original/translation pairs line up as two-page spreads.
            continue
        for p in render(translations[i] or "(blank page)", "STSong-Light", 1.6,
                         f"中文 — 第 {i + 1} 页").pages:
            writer.add_page(p)
    with open(out_path, "wb") as f:
        writer.write(f)
