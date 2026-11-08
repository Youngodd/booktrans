"""Make text safe to draw: no control codes, replacement characters or unassigned code points."""
import unicodedata

# Format characters that shape or order text and must stay (joiners, bidi marks)
_KEEP_FORMAT = {"‌", "‍", "‎", "‏", "؜", "‪", "‫", "‬",
                "‭", "‮", "⁦", "⁧", "⁨", "⁩"}


def clean_text(text):
    """`text` in NFC without characters that draw as nothing, a box or a wrong glyph.

    A model reply or a badly decoded file can hold U+FFFD (the replacement character),
    control codes, lone surrogates, private-use or unassigned code points, zero-width
    spaces and a byte-order mark; none of them has a glyph. Newlines stay.
    """
    out = []
    for ch in unicodedata.normalize("NFC", text):
        if ch == "\t":
            out.append(" ")
            continue
        cat = unicodedata.category(ch)
        if ch == "\n" or cat not in ("Cc", "Cs", "Co", "Cn", "Cf") and ch != "�":
            out.append(ch)
        elif cat == "Cf" and ch in _KEEP_FORMAT:
            out.append(ch)
    return "".join(out)
