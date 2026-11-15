"""Settings to suggest for a book as soon as it is uploaded, each with its reason.

Worked out from the file alone: no model call and nothing spent, since this runs before the
user has given an API key. Only what the file gives evidence for is suggested; a setting it
says nothing about is left out and keeps its default. The user sees the reasons and can
change every value.
"""
from pathlib import Path

from . import languages

LONG_BOOK = 40    # pages: longer than this, a trial of the first pages is suggested
TRIAL_PAGES = 10
SAMPLE = 12       # PDF pages looked at for a text layer
MIN_TEXT_CHARS = 20
SCAN_SHARE = 0.3  # this share of sampled pages without text makes the book a scan
SAME_FORMAT = {".pdf": "pdf", ".epub": "epub", ".docx": "docx", ".md": "md", ".markdown": "md"}


def _pdf_facts(book):
    """{"sampled", "no_text", "scans"}: pages looked at, how many have no text layer, and how
    many are a page-sized picture."""
    import fitz
    from .layout import has_page_image
    with fitz.open(str(book)) as doc:
        n = len(doc)
        step = max(n / SAMPLE, 1)
        picked = sorted({int(k * step) for k in range(min(SAMPLE, n))})
        no_text = sum(1 for i in picked if len(doc[i].get_text().strip()) < MIN_TEXT_CHARS)
        scans = sum(1 for i in picked if has_page_image(doc[i]))
    return {"sampled": len(picked), "no_text": no_text, "scans": scans}


def recommend(book, total=0, language=""):
    """{"settings": {name: value}, "reasons": {name: {"en": sentence, "zh": sentence}}} for the book.

    total      its number of pages (pipeline.total_pages), 0 if unknown
    language   its detected language code (pipeline.detect_book_language), "" if unknown

    The names are those of the start request: source, target, ocr, output_format,
    output_mode, pages, review_names. Never raises: a file that cannot be looked at gets
    fewer suggestions, not an error.
    """
    settings, reasons = {}, {}

    def suggest(name, value, en, zh):
        settings[name], reasons[name] = value, {"en": en, "zh": zh}

    ext = Path(book).suffix.lower()
    if language in languages.LANGUAGES:
        suggest("source", language, f"The text reads as {languages.name(language)}.",
                f"书中文字识别为{languages.native_name(language)}。")
        if language.split("-")[0] == languages.DEFAULT_TARGET.split("-")[0]:
            suggest("target", "en", f"The book is already in {languages.name(language)}, "
                                    "so English is suggested as the language to translate into.",
                    "这本书本身就是中文，所以建议翻译成英文。")
    if ext == ".pdf":
        try:
            facts = _pdf_facts(book)
        except Exception:
            facts = None
        if facts and facts["sampled"]:
            if facts["no_text"] / facts["sampled"] >= SCAN_SHARE:
                suggest("ocr", True, f"{facts['no_text']} of {facts['sampled']} pages looked at have no text "
                                     "layer (a scan), so they must be read with OCR first.",
                        f"抽查的 {facts['sampled']} 页中有 {facts['no_text']} 页没有文字层（扫描件），需要先用 OCR 识别。")
            else:
                suggest("ocr", False, "The pages have a text layer, so OCR is not needed.",
                        "页面带有文字层，不需要 OCR。")
    if ext in SAME_FORMAT:
        fmt = SAME_FORMAT[ext]
        en, zh = {"pdf": ("A PDF written as PDF keeps its page layout, pictures and tables in place.",
                          "PDF 输出为 PDF，可以保留原来的页面版式、图片和表格。"),
                  "epub": ("An EPUB written as EPUB keeps its own styles and pictures and still fits any screen.",
                           "EPUB 输出为 EPUB，可以保留原书的样式和图片，并适应各种屏幕。"),
                  "docx": ("A Word file written as Word stays editable, with its pictures and tables.",
                           "Word 输出为 Word，仍可编辑，图片和表格都在。"),
                  "md": ("A Markdown file written as Markdown keeps its marks, pictures and tables.",
                         "Markdown 输出为 Markdown，可以保留标记、图片和表格。")}[fmt]
        suggest("output_format", fmt, en, zh)
    elif ext == ".txt":
        suggest("output_format", "epub", "Plain text has no layout to keep; an EPUB fits any screen.",
                "纯文本没有版式可保留，EPUB 可以适应各种屏幕。")
    suggest("output_mode", "bilingual", "Each passage is followed by its translation, so you can check "
                                        "the translation against the original.",
            "每段原文后面紧跟译文，方便对照检查。")
    if total > LONG_BOOK:
        suggest("pages", f"1-{TRIAL_PAGES}", f"The book has {total} pages: translate the first {TRIAL_PAGES} "
                                             "to check the quality and the cost before paying for all of it.",
                f"全书共 {total} 页：先翻译前 {TRIAL_PAGES} 页，看看质量和费用，再决定是否翻译全书。")
        if language in languages.NAME_CAPITALS:
            suggest("review_names", True, "In a long book a name can be translated two ways; checking the "
                                          "list of names first keeps each one the same throughout.",
                    "长书里同一个名字容易出现两种译法；先核对名称表，可以让每个名字全书一致。")
    return {"settings": settings, "reasons": reasons}
