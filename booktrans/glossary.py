"""A per-book glossary, so a name is translated the same way on every page.

Pages are translated one request at a time, so without help the model renders "Boyle" as
波义耳 on one page and 玻意耳 on another. The glossary is built once: capitalised names that
repeat are found locally (free), then the model fixes one Chinese rendering for each. Every
page request then carries the entries that occur on that page.
"""
import re
from collections import defaultdict

from .backends.base import AuthError, BackendError, complete
from .fsutil import read_json, write_json
from .prompts import GLOSSARY_NOTE, glossary_prompt

LOWER = r"[^\W\d_]"  # any letter, accented ones included (Kekulé)
WORD = rf"[A-ZÀ-ÖØ-Þ]{LOWER}*(?:[-'’]{LOWER}+)*"
PHRASE = re.compile(rf"\b{WORD}(?:\s+(?:(?:of|de|von|van|der|la|du)\s+)?{WORD})*")
SENTENCE_START = re.compile(r"(?:^|[.!?:]['\"”’)]*\s+)$")
STOP = {
    "The", "A", "An", "In", "On", "At", "Of", "For", "To", "And", "But", "Or", "It", "He",
    "She", "They", "We", "You", "His", "Her", "Its", "Their", "This", "That", "These",
    "Those", "There", "As", "If", "When", "While", "Chapter", "Figure", "Fig", "Table",
    "Section", "Part", "Page", "Volume", "Mr", "Mrs", "Ms", "Dr", "St", "January",
    "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
}
MAX_TERMS = 300       # candidates sent to the model per book
CHUNK = 120           # entries per glossary request
MAX_NOTE_TERMS = 60   # entries added to one page request


def _clean(m, at_start):
    """(term, start) from a matched phrase, or ("", 0) if it is not a name.

    Leading stop words go ("In Oxford" -> "Oxford"), and so does a first word that is only
    capitalised because it starts a sentence ("Then Boyle" -> "Boyle", "However" -> nothing).
    """
    words = list(re.finditer(r"\S+", m.group()))
    stripped = False
    while words and words[0].group() in STOP:
        words.pop(0)
        stripped = True
    if at_start and not stripped and words:
        words.pop(0)
    if not words:
        return "", 0
    term = re.sub(r"['’]s$", "", " ".join(w.group() for w in words))
    if len(words) > 1 and term.isupper():  # an all-caps heading
        return "", 0
    return (term, m.start() + words[0].start()) if len(term) >= 3 else ("", 0)


def candidates(texts, min_count=2, max_terms=MAX_TERMS):
    """[(term, example sentence)] for names that repeat in `texts`, most frequent first.

    A single capitalised word only counts in mid-sentence, where the capital means a name.
    """
    count = defaultdict(int)
    example = {}
    for text in texts:
        for m in PHRASE.finditer(text):
            at_start = bool(SENTENCE_START.search(text[max(0, m.start() - 8):m.start()]))
            term, start = _clean(m, at_start)
            if not term:
                continue
            count[term] += 1
            if term not in example:
                a = max(0, m.start() - 80)
                example[term] = " ".join(text[a:m.end() + 80].split())
    terms = sorted((t for t, n in count.items() if n >= min_count),
                   key=lambda t: -count[t])[:max_terms]
    return [(t, example[t]) for t in terms]


_COMMENT = re.compile(r"(?:^|\s)#")  # a # that starts the line or follows a space; "C#" is not a comment
HEADER = ("# Book Translator glossary: one `original=translation` per line.\n"
          "# Edit it, then load it with --glossary FILE (or import it in the app).\n")


def _split(line):
    """(term, rendering) of one line: split at the first `=`, else at a tab or comma."""
    if "=" in line:
        term, _, zh = line.partition("=")
    else:
        parts = re.split(r"\s*[\t,]\s*", line, maxsplit=1)
        term, zh = (parts + [""])[:2]
    return term.strip(), zh.strip()


def parse_text(text, strict=False):
    """The entries of a glossary text: `original=translation` lines, # starts a comment.

    Lenient (the default) skips lines it cannot read. With strict=True such a line raises a
    ValueError that names it, so an uploaded file with a typo is reported, never half-read.
    """
    glossary = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = _COMMENT.split(raw, maxsplit=1)[0].strip()
        if not line:
            continue
        term, zh = _split(line)
        if term and zh:
            if strict:
                check_entry(term, zh, f"Line {n}: ")
            glossary[term] = zh
        elif strict:
            raise ValueError(f"Line {n}: expected `original=translation`, got {raw.strip()[:60]!r}.")
    return glossary


def parse_file(path):
    """Read `English=中文` lines (also tab or comma separated); # starts a comment."""
    with open(path, encoding="utf-8-sig") as f:  # Notepad adds a BOM
        return parse_text(f.read())


MAX_ENTRY_LEN = 80  # characters in a term or a rendering


def check_entry(term, zh, where=""):
    """ValueError unless the pair can be saved in a glossary file and read back unchanged."""
    if not term.strip() or len(term) > MAX_ENTRY_LEN or len(zh) > MAX_ENTRY_LEN:
        raise ValueError(f"{where}A glossary entry is empty or too long (at most {MAX_ENTRY_LEN} characters).")
    if "=" in term or "\n" in term + zh or "\r" in term + zh or _COMMENT.search(term) or _COMMENT.search(zh):
        raise ValueError(f"{where}A glossary entry may not contain a line break, a `=` in the original, "
                         f"or a # after a space: {term[:30]!r}.")


def dumps(glossary):
    """The glossary as text that parse_text/--glossary read back: entries with a rendering,
    sorted, one `original=translation` per line, preceded by a short header."""
    lines = []
    for term, zh in sorted(glossary.items(), key=lambda p: p[0].lower()):
        if not zh:
            continue
        try:
            check_entry(term, zh)
        except ValueError:  # cannot be written so that it reads back the same: leave it out
            continue
        lines.append(f"{term}={zh}")
    return HEADER + "\n".join(lines) + ("\n" if lines else "")


def load(path):
    return read_json(path)


def save(path, glossary):
    write_json(path, glossary, indent=1, sort_keys=True)


def mentioned(term, text):
    return re.search(rf"(?<!{LOWER}){re.escape(term)}(?!{LOWER})", text) is not None


def build(backend, all_texts, needed_texts, glossary, progress=None, source="en", target="zh-CN"):
    """Add to `glossary` the names of `needed_texts` that it lacks; returns the new entries.

    Names are counted over `all_texts` (the whole book), so a name seen only once in the
    pages being translated still gets the same rendering as in the rest of the book. An
    entry with "" means "no fixed rendering needed" and is not asked again.
    """
    needed = "\n".join(needed_texts)
    todo = [(t, ex) for t, ex in candidates(all_texts)
            if t not in glossary and mentioned(t, needed)]
    todo.sort(key=lambda p: (p[0].split()[-1].lower(), p[0]))  # variants of a name sit together
    added = {}
    for start in range(0, len(todo), CHUNK):
        chunk = todo[start:start + CHUNK]
        src = "\n".join(f"[{n}] {t} | {ex}" for n, (t, ex) in enumerate(chunk, 1))
        try:
            out = complete(backend, glossary_prompt(source, target), src, 4096)
        except AuthError:
            raise
        except BackendError:
            break  # the glossary is a help, not a requirement: translate without the rest
        parts = re.split(r"(?m)^\[(\d+)\][ \t]*", out)
        got = {int(parts[k]): parts[k + 1].strip() for k in range(1, len(parts) - 1, 2)}
        for n, (t, _) in enumerate(chunk, 1):
            if n in got:
                zh = got[n].replace("**", "")
                added[t] = "" if zh in ("~", "") else zh
        glossary.update(added)
        if progress:
            progress("glossary", min(start + CHUNK, len(todo)), len(todo))
    return added


def note(glossary, text):
    """The glossary lines to add to a request for `text` (only the entries it mentions)."""
    if not glossary:
        return ""
    hits = sorted((t for t, zh in glossary.items() if zh and mentioned(t, text)),
                  key=lambda t: -len(t))[:MAX_NOTE_TERMS]
    return GLOSSARY_NOTE + "\n".join(f"{t} = {glossary[t]}" for t in hits) if hits else ""
