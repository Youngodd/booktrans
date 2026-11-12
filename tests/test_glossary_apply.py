"""Download the glossary, edit it, and apply the edits to the pages already translated."""
import fitz
import pytest

from booktrans import cli, glossary, pipeline, translate
from booktrans.fsutil import read_json
from tests.conftest import FakeBackend
from tests.test_web import KEY, glossary_factory, make_client, upload, wait, wait_glossary  # noqa: F401


# ---- the text format ------------------------------------------------------------------------

def test_dumps_round_trips_through_parse_text_and_parse_file(tmp_path):
    g = {"Boyle": "波义耳", "Isaac Newton": "艾萨克·牛顿", "Kekulé": "凯库勒", "Oxford": "", "C#": "C#",
         "Smith, John": "史密斯", "a=b": "bad term", "x": "has\nbreak"}
    text = glossary.dumps(g)
    assert text.startswith("#") and text.endswith("\n")
    back = glossary.parse_text(text, strict=True)
    assert back == {"Boyle": "波义耳", "Isaac Newton": "艾萨克·牛顿", "Kekulé": "凯库勒", "C#": "C#",
                    "Smith, John": "史密斯"}                  # empty and unrepresentable entries are left out
    p = tmp_path / "g.txt"
    p.write_text(text, encoding="utf-8")
    assert glossary.parse_file(p) == back


def test_dumps_of_an_empty_glossary_is_just_the_header():
    assert glossary.dumps({}) == glossary.HEADER == glossary.dumps({"A": ""})


@pytest.mark.parametrize("text", ["Boyle", "Boyle=", "=波义耳", "ok=好\nnonsense line", "a=b # c\nx", "a=" + "x" * 81])
def test_strict_parsing_names_the_bad_line(text):
    with pytest.raises(ValueError, match="Line"):
        glossary.parse_text(text, strict=True)


def test_lenient_parsing_still_skips_bad_lines():
    assert glossary.parse_text("Boyle\nOxford=牛津\n=x\n# note\n") == {"Oxford": "牛津"}


def test_comments_start_at_a_hash_after_a_space_only():
    assert glossary.parse_text("C#=C#  # the language\nA = B # note") == {"C#": "C#", "A": "B"}


def test_the_equals_sign_wins_over_a_comma():
    assert glossary.parse_text("Smith, John=史密斯") == {"Smith, John": "史密斯"}


# ---- which pages a glossary edit affects --------------------------------------------------------

PAGES = ["Boyle met Newton.", "Only Oxford here.", "Nothing named at all here."]


def three_page_book(tmp_path):
    """A TXT book whose three paragraphs each fill most of a page, so no two share a page."""
    book = tmp_path / "b.txt"
    book.write_text("\n\n".join(p + " " + "filler " * 200 for p in PAGES), encoding="utf-8")
    return book


def test_changed_added_and_removed_terms_affect_exactly_their_pages(tmp_path):
    book = three_page_book(tmp_path)
    out = tmp_path / "o.pdf"
    gpath = tmp_path / "o.glossary.json"
    glossary.save(gpath, {"Boyle": "波义耳", "Oxford": "牛津"})
    pipeline.translate_book(book, out, FakeBackend(), source="en", auto_glossary=False)
    assert len(read_json(tmp_path / "o.cache.json")) == 3
    assert pipeline.glossary_changes(book, out)["pages"] == []         # nothing edited yet

    glossary.save(gpath, {"Boyle": "玻意耳", "Oxford": "牛津"})       # changed
    assert pipeline.glossary_changes(book, out)["pages"] == [1]
    glossary.save(gpath, {"Boyle": "波义耳", "Oxford": "牛津", "Newton": "牛顿"})  # added
    assert pipeline.glossary_changes(book, out)["pages"] == [1]
    glossary.save(gpath, {"Boyle": "波义耳", "Oxford": ""})            # removed (empty = no fixed rendering)
    assert pipeline.glossary_changes(book, out)["pages"] == [2]
    glossary.save(gpath, {"Zebra": "斑马"})                           # a name no page mentions
    assert pipeline.glossary_changes(book, out)["pages"] == [1, 2]    # Boyle/Oxford dropped; Zebra nowhere


def test_apply_translates_only_the_affected_pages_and_keeps_the_rest(tmp_path):
    book = three_page_book(tmp_path)
    out = tmp_path / "o.pdf"
    gpath = tmp_path / "o.glossary.json"
    glossary.save(gpath, {"Boyle": "波义耳", "Oxford": "牛津"})
    first = FakeBackend()
    pipeline.translate_book(book, out, first, source="en", auto_glossary=False)
    before = read_json(tmp_path / "o.cache.json")

    glossary.save(gpath, {"Boyle": "玻意耳", "Oxford": "牛津"})
    second = FakeBackend()
    pipeline.translate_book(book, out, second, source="en", refresh_glossary=True)
    after = read_json(tmp_path / "o.cache.json")
    assert len(second.calls) == 1 and "Boyle" in second.calls[0]      # one request, for page 1 only
    assert before.keys() == after.keys()
    assert after["1"] == before["1"] and after["2"] == before["2"]    # untouched pages keep their cache entry
    assert pipeline.glossary_changes(book, out)["pages"] == []         # applied: nothing left to apply
    assert fitz.open(out).page_count == 6                             # the output was rebuilt (original + translation)


def test_apply_translates_with_the_new_rendering(tmp_path):
    book = tmp_path / "b.txt"
    book.write_text("Boyle met Newton in Oxford. " + "filler " * 100, encoding="utf-8")
    out = tmp_path / "o.pdf"
    glossary.save(tmp_path / "o.glossary.json", {"Boyle": "波义耳"})
    pipeline.translate_book(book, out, FakeBackend(), source="en", auto_glossary=False)
    glossary.save(tmp_path / "o.glossary.json", {"Boyle": "玻意耳"})
    systems = []
    fb = FakeBackend()
    orig = fb.complete
    fb.complete = lambda system, user, max_tokens=4096: (systems.append(system), orig(system, user))[1]
    pipeline.translate_book(book, out, fb, source="en", refresh_glossary=True)
    assert systems and all("Boyle = 玻意耳" in s for s in systems)


def test_apply_does_not_run_the_automatic_glossary(tmp_path):
    book = tmp_path / "b.txt"
    book.write_text("Boyle met Boyle again. " * 30, encoding="utf-8")
    out = tmp_path / "o.pdf"
    glossary.save(tmp_path / "o.glossary.json", {"Boyle": "波义耳"})
    pipeline.translate_book(book, out, FakeBackend(), source="en", auto_glossary=False)
    glossary.save(tmp_path / "o.glossary.json", {"Boyle": "玻意耳"})
    fb = FakeBackend()
    pipeline.translate_book(book, out, fb, source="en", refresh_glossary=True)
    assert all(" | " not in c for c in fb.calls)                      # no name-collecting request


def test_pages_translated_before_tracking_are_treated_as_possibly_changed(tmp_path):
    book = tmp_path / "b.txt"
    book.write_text("Boyle spoke. " + "filler " * 100 + "\n\n" + "Nothing here. " + "filler " * 100, encoding="utf-8")
    out = tmp_path / "o.pdf"
    glossary.save(tmp_path / "o.glossary.json", {"Boyle": "波义耳"})
    pipeline.translate_book(book, out, FakeBackend(), source="en", auto_glossary=False)
    (tmp_path / "o.glossary-used.json").unlink()                      # as if made by an older version
    assert pipeline.glossary_changes(book, out)["pages"] == [1]       # only the page that mentions a name


def test_layout_pdf_pages_are_tracked_too(tmp_path, text_pdf):
    out = tmp_path / "o.pdf"
    glossary.save(tmp_path / "o.glossary.json", {"Chapter": "章"})
    pipeline.translate_book(text_pdf, out, FakeBackend(), source="en", auto_glossary=False)
    assert pipeline.glossary_changes(text_pdf, out)["pages"] == []
    glossary.save(tmp_path / "o.glossary.json", {"Chapter": "篇"})
    assert pipeline.glossary_changes(text_pdf, out)["pages"] == [1, 2, 3]
    fb = FakeBackend()
    pipeline.translate_book(text_pdf, out, fb, source="en", refresh_glossary=True)
    assert len(fb.calls) == 3 and pipeline.glossary_changes(text_pdf, out)["pages"] == []


def test_apply_cannot_be_combined_with_finishing_for_free(tmp_path):
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.")
    with pytest.raises(ValueError):
        pipeline.translate_book(tmp_path / "b.txt", tmp_path / "o.pdf", FakeBackend(),
                                only_cached=True, refresh_glossary=True)


def test_apply_respects_the_spend_limit(tmp_path):
    from booktrans.spend import Meter, SpendLimitReached
    from tests.conftest import PricedBackend
    book = tmp_path / "b.txt"
    book.write_text("\n\n".join(f"Boyle page {n}. " + "filler " * 200 for n in range(4)), encoding="utf-8")
    out = tmp_path / "o.pdf"
    glossary.save(tmp_path / "o.glossary.json", {"Boyle": "波义耳"})
    pipeline.translate_book(book, out, FakeBackend(), source="en", auto_glossary=False)
    glossary.save(tmp_path / "o.glossary.json", {"Boyle": "玻意耳"})
    with pytest.raises(SpendLimitReached):
        pipeline.translate_book(book, out, PricedBackend(), source="en", refresh_glossary=True,
                                meter=Meter(1.5, tmp_path / "o.spend.json", prices={"fake": {"text": (500.0, 500.0)}}))


# ---- the web flow -------------------------------------------------------------------------------

NAMES = "He met Boyle in Oxford. She met Boyle in Oxford. " * 3


def finished_job(c):
    job = upload(c, "My Book.txt", NAMES.encode()).json()
    url = f"/api/jobs/{job['id']}"
    c.post(url + "/glossary/draft", json={"api_key": KEY})
    wait_glossary(c, job["id"])
    return job["id"], url


def test_download_is_available_right_after_the_draft_and_reads_back(make_client):
    c = make_client(glossary_factory)
    jid, url = finished_job(c)
    r = c.get(url + "/glossary/download")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "My Book_glossary_zh-CN.txt" in r.headers["content-disposition"]
    assert glossary.parse_text(r.text, strict=True) == {"Boyle": "波义耳", "Oxford": "牛津"}
    assert r.headers["cache-control"] == "no-store"


def test_download_says_so_when_there_is_nothing_or_it_is_still_building(make_client):
    c = make_client(glossary_factory)
    job = upload(c, "b.txt", b"nothing named here at all, just lower case words " * 5).json()
    assert c.get(f"/api/jobs/{job['id']}/glossary/download").status_code == 404
    from booktrans.web.jobs import JobStore
    JobStore(c.app.state.store.root).write(job["id"], glossary_state="building")
    assert c.get(f"/api/jobs/{job['id']}/glossary/download").status_code == 409
    assert c.get("/api/jobs/" + "a" * 22 + "/glossary/download").status_code == 404


def test_import_replaces_renderings_and_reports_a_bad_line(make_client):
    c = make_client(glossary_factory)
    jid, url = finished_job(c)
    r = c.post(url + "/glossary/import", json={"text": "# edited\nBoyle=玻意耳\nNewton=牛顿\n"})
    assert r.status_code == 200 and r.json() == {"entries": 2}        # Oxford is no longer listed: dropped
    got = {e["term"]: e["zh"] for e in c.get(url + "/glossary").json()["entries"]}
    assert got == {"Boyle": "玻意耳", "Newton": "牛顿"}
    bad = c.post(url + "/glossary/import", json={"text": "Boyle=好\nthis line is wrong\n"})
    assert bad.status_code == 400 and "Line 2" in bad.json()["detail"]
    got = {e["term"]: e["zh"] for e in c.get(url + "/glossary").json()["entries"]}
    assert got == {"Boyle": "玻意耳", "Newton": "牛顿"}                # a rejected file changed nothing
    assert c.post(url + "/glossary/import", json={"text": "# only a comment\n"}).status_code == 400
    many = "\n".join(f"T{n}=x" for n in range(501))
    assert c.post(url + "/glossary/import", json={"text": many}).status_code == 400


def test_put_rejects_entries_that_could_not_be_downloaded_and_read_back(make_client):
    c = make_client(glossary_factory)
    jid, url = finished_job(c)
    for bad in ({"a=b": "x"}, {"a": "x\ny"}, {"a": "x # y"}, {"": "x"}, {"a": "x" * 81}, {"x" * 81: "y"}):
        assert c.put(url + "/glossary", json={"entries": bad}).status_code == 400


def test_changes_then_apply_end_to_end(make_client):
    seen = []

    def factory(key, provider="api"):
        base = glossary_factory(key, provider)
        orig = base.complete
        base.complete = lambda system, user, max_tokens=4096: (seen.append((system, user)), orig(system, user))[1]
        return base
    c = make_client(factory)
    job = upload(c, "b.txt", (NAMES + "\n\n" + "A plain page with no names in it. " * 60).encode()).json()
    url = f"/api/jobs/{job['id']}"
    c.post(url + "/glossary/draft", json={"api_key": KEY})
    wait_glossary(c, job["id"])
    assert c.post(url + "/start", json={"api_key": KEY}).status_code == 200
    assert wait(c, job["id"])["state"] == "done"
    assert c.get(url + "/glossary/changes").json()["pages"] == 0       # nothing edited yet

    # the user finds a wrong rendering in the downloaded file, fixes it and imports it back
    fixed = c.get(url + "/glossary/download").text.replace("波义耳", "玻意耳")
    assert c.post(url + "/glossary/import", json={"text": fixed}).status_code == 200
    ch = c.get(url + "/glossary/changes").json()
    assert ch["pages"] == 1 and ch["page_numbers"] == [1] and ch["translated"] >= 2
    assert ch["est_cny"] is not None and ch["est_cny"] > 0

    seen.clear()
    r = c.post(url + "/start", json={"api_key": KEY, "refresh_glossary": True})
    assert r.status_code == 200
    assert wait(c, job["id"])["state"] == "done"
    assert len(seen) == 1 and "Boyle" in seen[0][1] and "Boyle = 玻意耳" in seen[0][0]
    assert c.get(url + "/glossary/changes").json()["pages"] == 0       # applied
    # a later ordinary start does not translate again by itself
    seen.clear()
    c.post(url + "/start", json={"api_key": KEY})
    wait(c, job["id"])
    assert seen == []


def test_changes_import_and_apply_are_refused_while_the_job_runs(make_client):
    c = make_client(glossary_factory)
    jid, url = finished_job(c)
    from booktrans.web.jobs import JobStore
    JobStore(c.app.state.store.root).write(jid, state="running")
    assert c.get(url + "/glossary/changes").status_code == 409
    assert c.post(url + "/glossary/import", json={"text": "A=b"}).status_code == 409
    assert c.put(url + "/glossary", json={"entries": {"A": "b"}}).status_code == 409
    assert c.post(url + "/start", json={"api_key": KEY, "refresh_glossary": True}).status_code == 409


def test_apply_and_finish_for_free_cannot_be_combined(make_client):
    c = make_client(glossary_factory)
    jid, url = finished_job(c)
    assert c.post(url + "/start", json={"refresh_glossary": True, "only_cached": True}).status_code == 400


def test_the_apply_flag_does_not_stick_to_later_starts(make_client):
    c = make_client(glossary_factory)
    jid, url = finished_job(c)
    c.post(url + "/start", json={"api_key": KEY, "refresh_glossary": True})
    wait(c, jid)
    c.post(url + "/start", json={"api_key": KEY})
    wait(c, jid)
    assert c.app.state.store.read(jid)["refresh_glossary"] is False


# ---- the command line -------------------------------------------------------------------------------

def cli_run(monkeypatch, argv, backend):
    monkeypatch.setattr("sys.argv", ["booktrans", *argv])
    monkeypatch.setattr(cli, "make_backend", lambda *a, **k: backend)
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    cli.main()


def test_cli_export_edit_apply(monkeypatch, tmp_path, capsys):
    book = tmp_path / "b.txt"
    book.write_text(NAMES + "\n\n" + "A plain page with no names in it. " * 60, encoding="utf-8")
    names = tmp_path / "names.txt"
    fb = glossary_factory(KEY)
    cli_run(monkeypatch, [str(book), "--export-glossary", str(names), "--backend", "api", "--max-spend", "0"], fb)
    assert not (tmp_path / "b_bilingual.pdf").exists()                # it stopped before translating
    assert glossary.parse_file(names) == {"Boyle": "波义耳", "Oxford": "牛津"}

    # translate with the file, then edit it and apply
    cli_run(monkeypatch, [str(book), "--glossary", str(names), "--backend", "api", "--max-spend", "0"], glossary_factory(KEY))
    names.write_text(names.read_text(encoding="utf-8").replace("波义耳", "玻意耳"), encoding="utf-8")
    again = FakeBackend()
    capsys.readouterr()
    cli_run(monkeypatch, [str(book), "--glossary", str(names), "--apply-glossary", "--backend", "api",
                          "--max-spend", "0"], again)
    out = capsys.readouterr().out
    assert "1 of" in out and "pages 1" in out.replace("pages: ", "pages ")
    assert len(again.calls) == 1 and "Boyle" in again.calls[0]
    # nothing left to apply: no calls, and it says so
    none = FakeBackend()
    cli_run(monkeypatch, [str(book), "--glossary", str(names), "--apply-glossary", "--backend", "api",
                          "--max-spend", "0"], none)
    assert none.calls == [] and "None of the" in capsys.readouterr().out


def test_cli_apply_before_anything_is_translated(monkeypatch, tmp_path, capsys):
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.", encoding="utf-8")
    fb = FakeBackend()
    cli_run(monkeypatch, [str(tmp_path / "b.txt"), "--apply-glossary", "--backend", "api"], fb)
    assert fb.calls == [] and "Nothing has been translated" in capsys.readouterr().out


def test_cli_apply_with_finish_partial_is_refused(monkeypatch, tmp_path):
    (tmp_path / "b.txt").write_text("Hello there, this is a short book.", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli_run(monkeypatch, [str(tmp_path / "b.txt"), "--apply-glossary", "--finish-partial"], FakeBackend())


def test_cli_export_without_names_writes_no_file(monkeypatch, tmp_path, capsys):
    (tmp_path / "b.txt").write_text("all lower case words and nothing more to see here " * 20, encoding="utf-8")
    cli_run(monkeypatch, [str(tmp_path / "b.txt"), "--export-glossary", str(tmp_path / "n.txt"), "--backend", "api"],
            FakeBackend())
    assert not (tmp_path / "n.txt").exists() and "No names" in capsys.readouterr().out


# ---- the pages --------------------------------------------------------------------------------------

def test_the_names_controls_and_strings_exist_in_both_languages():
    import re
    from pathlib import Path
    static = Path(__file__).parent.parent / "booktrans" / "web" / "static"
    ids = ("btn-names-download", "btn-names-import", "names-file", "btn-names-apply", "btn-names-review")
    for lang in ("en", "zh"):
        html = (static / f"desktop.{lang}.html").read_text(encoding="utf-8")
        for i in ids:
            assert f'id="{i}"' in html, (lang, i)
    names = {"namesApply", "namesClose", "namesReviewIntro", "namesSaved", "importedOk", "noChanges",
             "applyConfirm", "applyGo"}
    js = {lang: (static / f"desktop.{lang}.js").read_text(encoding="utf-8") for lang in ("en", "zh")}
    for lang in ("en", "zh"):
        for k in names:
            assert re.search(rf"\b{k}:", js[lang]), (lang, k)
    app_js = (static / "desktop.js").read_text(encoding="utf-8")
    for k in names:
        assert f"T.{k}" in app_js, k
    assert "localStorage" not in app_js
