"""Words must keep their spaces when a line's text spans are joined."""
import fitz

from booktrans.layout import _spans, _text, extract_blocks


def span(text, x0, x1, size=12):
    return {"text": text, "bbox": [x0, 0, x1, 14], "size": size}


def line(*spans):
    return {"spans": list(spans)}


def test_a_space_kept_as_a_span_of_its_own_is_not_lost():
    """A browser-printed PDF stores 'Hong', ' ', 'Kong' as three spans."""
    ln = line(span("Hong", 148, 178), span(" ", 177, 181), span("Kong", 180, 209))
    assert _text(_spans(ln)) == "Hong Kong"


def test_a_gap_with_no_space_character_becomes_a_space():
    ln = line(span("Isle", 100, 124), span("of", 130, 142), span("Man", 148, 172))
    assert _text(_spans(ln)) == "Isle of Man"


def test_pieces_of_one_word_are_not_split():
    ln = line(span("re", 100, 112), span("sult", 112.5, 136))   # a bold or italic part inside a word
    assert _text(_spans(ln)) == "result"


def test_spaces_inside_a_span_and_extra_spaces_are_normalised():
    ln = line(span("Hungary - ", 100, 160), span(" ", 160, 163), span("Budapest", 163, 215))
    assert _text(_spans(ln)) == "Hungary - Budapest"


def test_chinese_and_japanese_are_not_given_spaces():
    ln = line(span("这是", 100, 124), span("一个", 130, 154), span("测试", 160, 184))
    assert _text(_spans(ln)) == "这是一个测试"
    ln = line(span("日本", 100, 124), span(" ", 124, 127), span("語", 127, 139))
    assert _text(_spans(ln)) == "日本語"
    # but a word between CJK and Latin text keeps its spaces
    ln = line(span("使用", 100, 124), span(" ", 124, 127), span("Python", 127, 170))
    assert _text(_spans(ln)) == "使用 Python"


def test_blank_and_leading_spaces_do_not_make_a_line():
    assert _spans(line(span(" ", 0, 3), span("\t", 3, 6))) == []
    assert _text(_spans(line(span(" ", 0, 3), span("Word", 3, 40)))) == "Word"


def test_in_a_real_pdf_words_set_apart_by_a_gap_keep_their_space(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    x = 72
    for word in ("Isle", "of", "Man", "ferry"):      # four separate text runs, no space characters
        page.insert_text((x, 100), word, fontsize=12)
        x += fitz.get_text_length(word, fontsize=12) + 4.5
    doc.save(tmp_path / "g.pdf")
    texts = [b["text"] for b in extract_blocks(fitz.open(tmp_path / "g.pdf")[0])]
    assert texts == ["Isle of Man ferry"]


def test_a_paragraph_keeps_its_spaces_end_to_end(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(72, 100, 300, 300),
                        "The quick brown fox jumps over the lazy dog and keeps running far away.", fontsize=11)
    doc.save(tmp_path / "p.pdf")
    (block,) = extract_blocks(fitz.open(tmp_path / "p.pdf")[0])
    assert block["text"] == "The quick brown fox jumps over the lazy dog and keeps running far away."
