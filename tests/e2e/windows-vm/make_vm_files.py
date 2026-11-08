"""Make the small test books the Windows scripts expect, then push them with utmctl (see README).
usage: python make_vm_files.py OUTDIR      (needs PyMuPDF and EbookLib: the project venv has both)"""
import sys
from pathlib import Path
import fitz
from ebooklib import epub

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)

def make_pdf(path, pages):
    d = fitz.open()
    for n in range(pages):
        p = d.new_page(); p.insert_text((72, 100), f"Page heading {n+1}", fontsize=20)
        p.insert_textbox(fitz.Rect(72, 130, 500, 300), f"Body paragraph {n+1} of the book, long enough to wrap onto several lines of the page. Dr Alpha Zeta met Professor Beta Omega.", fontsize=11)
    d.save(path)

make_pdf(out / "book12.pdf", 12); make_pdf(out / "long300.pdf", 300); make_pdf(out / "zh4.pdf", 4)
b = epub.EpubBook(); b.set_identifier("x1"); b.set_title("Test"); b.set_language("en"); chs = []
for i in range(3):
    c = epub.EpubHtml(title=f"C{i}", file_name=f"c{i}.xhtml", lang="en")
    c.content = f"<h1>Chapter {i}</h1><p>This is paragraph one of chapter {i}, with enough words to be a paragraph.</p><p>Second paragraph of chapter {i} here.</p>"
    b.add_item(c); chs.append(c)
b.toc = chs; b.add_item(epub.EpubNcx()); b.add_item(epub.EpubNav()); b.spine = ["nav"] + chs
epub.write_epub(str(out / "book.epub"), b)
(out / "book.txt").write_text("\n\n".join(f"Paragraph {i}. This is a plain text paragraph for the test." for i in range(8)), encoding="utf-8")
print("wrote", sorted(p.name for p in out.iterdir()))
