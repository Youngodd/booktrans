import re

from booktrans import glossary
from booktrans.backends.base import AuthError, BackendError
from booktrans.pipeline import translate_book
from booktrans.translate import translate, translate_blocks
from tests.conftest import FakeBackend

BOOK = ("He met Boyle in Oxford. Later Boyle wrote at Oxford. Then Newton read Boyle. "
        "Later Newton replied to Newton. The weather was fine.")


def test_candidates_find_repeated_names_only():
    found = [t for t, _ in glossary.candidates([BOOK])]
    assert "Boyle" in found and "Oxford" in found and "Newton" in found
    assert "The" not in found and "Then" not in found and "Later" not in found


def test_single_capitalised_word_at_sentence_start_is_not_a_name():
    assert glossary.candidates(["Boyle ran. Boyle sat."]) == []
    assert [t for t, _ in glossary.candidates(["See Boyle. Ask Boyle."])] == ["Boyle"]


def test_possessive_and_leading_stop_words_are_removed():
    found = [t for t, _ in glossary.candidates(["Of Boyle's law. In Boyle's time."])]
    assert found == ["Boyle"]


def test_all_caps_headings_are_not_terms():
    assert glossary.candidates(["see THE GREAT WAR now. see THE GREAT WAR again."]) == []


def reply_with(table):
    """A glossary answer: `[n] <zh>` for the entry whose term is in `table`, else `~`."""
    def reply(user):
        out = []
        for line in user.splitlines():
            m = re.match(r"\[(\d+)\] ([^|]+?) \|", line)
            if m:
                out.append(f"[{m.group(1)}] {table.get(m.group(2), '~')}")
        return "\n".join(out)
    return reply


def test_build_asks_once_and_skips_known_terms():
    b = FakeBackend(reply=reply_with({"Boyle": "波义耳", "Oxford": "牛津"}))
    g = {"Newton": "牛顿"}
    added = glossary.build(b, [BOOK], [BOOK], g)
    assert g == {"Newton": "牛顿", "Boyle": "波义耳", "Oxford": "牛津"}
    assert added == {"Boyle": "波义耳", "Oxford": "牛津"}
    assert len(b.calls) == 1 and "Newton |" not in b.calls[0]
    glossary.build(b, [BOOK], [BOOK], g)
    assert len(b.calls) == 1  # nothing new to ask


def test_terms_without_a_fixed_rendering_are_remembered_as_empty():
    b = FakeBackend(reply=reply_with({}))
    g = {}
    glossary.build(b, [BOOK], [BOOK], g)
    assert g and all(v == "" for v in g.values())
    glossary.build(b, [BOOK], [BOOK], g)
    assert len(b.calls) == 1


def test_build_only_covers_names_in_the_chosen_pages():
    b = FakeBackend(reply=reply_with({"Boyle": "波义耳"}))
    g = {}
    glossary.build(b, [BOOK, "Curie met Curie and Curie."], ["Boyle met Boyle."], g)
    assert "Curie" not in g and "Boyle" in g
    assert "Boyle |" in b.calls[0] and "Curie |" not in b.calls[0]


def test_build_survives_a_backend_error_but_not_a_bad_key():
    class Down(FakeBackend):
        def complete(self, *a, **k):
            raise BackendError("down")
    g = {}
    import booktrans.translate as t
    old, t.RETRY_DELAYS = t.RETRY_DELAYS, ()
    try:
        glossary.build(Down(), [BOOK], [BOOK], g)
        assert g == {}

        class Bad(FakeBackend):
            def complete(self, *a, **k):
                raise AuthError("no")
        try:
            glossary.build(Bad(), [BOOK], [BOOK], g)
            assert False
        except AuthError:
            pass
    finally:
        t.RETRY_DELAYS = old


def test_note_lists_only_entries_on_the_page():
    g = {"Boyle": "波义耳", "Curie": "居里", "Skip": ""}
    n = glossary.note(g, "Boyle's law and Skip")
    assert "Boyle = 波义耳" in n and "Curie" not in n and "Skip" not in n
    assert glossary.note(g, "nothing here") == "" and glossary.note({}, "Boyle") == ""


def test_mentioned_matches_whole_words():
    assert glossary.mentioned("Boyle", "Boyle's law") and not glossary.mentioned("Boyle", "Boylefield")


def test_translate_sends_the_glossary_with_the_page():
    seen = []
    b = FakeBackend()
    orig = b.complete
    b.complete = lambda system, user, max_tokens=4096: (seen.append(system), orig(system, user))[1]
    translate(b, "Boyle wrote.", {"Boyle": "波义耳"})
    translate_blocks(b, [{"text": "Boyle again"}], glossary={"Boyle": "波义耳"})
    assert all("Boyle = 波义耳" in s for s in seen) and len(seen) == 2


def test_parse_file(tmp_path):
    f = tmp_path / "g.txt"
    f.write_text("# names\nBoyle=波义耳\nOxford , 牛津  # city\nbad line\n", encoding="utf-8")
    assert glossary.parse_file(f) == {"Boyle": "波义耳", "Oxford": "牛津"}


def test_pipeline_builds_saves_and_applies_the_glossary(tmp_path):
    book = tmp_path / "b.txt"
    book.write_text(BOOK, encoding="utf-8")
    out = tmp_path / "b_bilingual.pdf"
    user_file = tmp_path / "mine.txt"
    user_file.write_text("Newton=牛顿\n", encoding="utf-8")
    b = FakeBackend(reply=lambda u: reply_with({"Boyle": "波义耳"})(u) if " | " in u else "译:" + u)
    translate_book(book, out, b, glossary_file=user_file)
    saved = glossary.load(out.with_suffix(".glossary.json"))
    assert saved["Boyle"] == "波义耳" and saved["Newton"] == "牛顿"
    translate_book(book, tmp_path / "again.pdf", b, auto_glossary=False)  # no new glossary call


def test_accented_names_are_kept_whole():
    assert [t for t, _ in glossary.candidates(["See Kekulé. Ask Kekulé."])] == ["Kekulé"]
    assert glossary.mentioned("Kekulé", "Kekulé's ring") and not glossary.mentioned("Kekul", "Kekulé")
