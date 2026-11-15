"""A book as blocks in reading order: what every format is read into and written from.

A block is a dict with a "type":

    heading   text, level (1-6)
    para      text
    list      text, level (nesting, from 0), ordered
    code      text (never translated)
    table     rows: [[cell text, ...], ...]
    figure    image (file name in the assets folder), alt
    break     a chapter boundary (no content)

After translation a text block also has "tr" and a table "tr_rows". Readers (blockreaders.py)
produce the blocks and save pictures in an assets folder; writers (blockwriters.py) read only
the blocks and that folder, so any input can become any output.
"""
import hashlib
from pathlib import Path

from .readers import CHARS_PER_PAGE

TEXT_TYPES = ("heading", "para", "list")
KEEP = "~"  # the translator's answer for text to leave as it is
MAX_UNIT_SEGMENTS = 40


def save_asset(assets, data, ext):
    """Store picture bytes in the `assets` folder under a name made from their content (the
    same picture twice is one file); returns the file name."""
    assets = Path(assets)
    assets.mkdir(parents=True, exist_ok=True)
    ext = (ext or "").lower().lstrip(".") or "bin"
    name = hashlib.sha1(data).hexdigest()[:16] + "." + ("jpg" if ext == "jpeg" else ext)
    path = assets / name
    if not path.exists():
        path.write_bytes(data)
    return name


def segments(blocks):
    """The pieces of text to translate, in order: [(block index, cell or None, text)].
    A cell is (row, column) of a table block."""
    out = []
    for k, b in enumerate(blocks):
        if b["type"] in TEXT_TYPES and b["text"].strip():
            out.append((k, None, b["text"]))
        elif b["type"] == "table":
            for r, row in enumerate(b["rows"]):
                for c, text in enumerate(row):
                    if text.strip():
                        out.append((k, (r, c), text))
    return out


def units(blocks):
    """The segments grouped into units of about a page (CHARS_PER_PAGE characters), each
    translated in one request and cached as one entry. A table is not cut between two units
    unless it is larger than a unit by itself."""
    out, cur, size = [], [], 0
    for seg in segments(blocks):
        n = len(seg[2])
        new_block = not cur or cur[-1][0] != seg[0]
        if cur and (len(cur) >= MAX_UNIT_SEGMENTS or (size + n > CHARS_PER_PAGE and
                                                      (new_block or size > 2 * CHARS_PER_PAGE))):
            out.append(cur)
            cur, size = [], 0
        cur.append(seg)
        size += n
    if cur:
        out.append(cur)
    return out


def unit_text(unit):
    """The source text of a unit as one string (for language detection and the glossary)."""
    return "\n\n".join(text for _, _, text in unit)


def apply(blocks, unit, translations):
    """Put a unit's translations into its blocks ("tr", or "tr_rows" for table cells)."""
    for (k, cell, _), tr in zip(unit, translations):
        b = blocks[k]
        if cell is None:
            b["tr"] = tr
        else:
            rows = b.setdefault("tr_rows", [[""] * len(row) for row in b["rows"]])
            rows[cell[0]][cell[1]] = tr


def translated(text, tr):
    """The translation to show for `text`: the original when there is none, or the
    translator said to keep it."""
    tr = (tr or "").strip()
    return text if not tr or tr == KEEP else tr


def pairs(block, bilingual):
    """What a text block shows: [(text, is the translation)] - the original then its
    translation, or only one of them."""
    text = block["text"]
    tr = (block.get("tr") or "").strip()
    if not tr or tr == KEEP or tr == text.strip():
        return [(text, False)]
    return [(text, False), (tr, True)] if bilingual else [(tr, True)]


def cell_pairs(block, r, c, bilingual):
    """The same for one table cell."""
    text = block["rows"][r][c]
    rows = block.get("tr_rows")
    return pairs({"text": text, "tr": rows[r][c] if rows else ""}, bilingual)
