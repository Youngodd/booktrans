"""The read-only summary on the progress card: what it says, and that it never holds a key."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_web import KEY, make_client, upload, wait  # noqa: F401

STATIC = Path(__file__).parent.parent / "booktrans" / "web" / "static"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

LANGS = [{"code": "en", "name": "English", "native": "English"},
         {"code": "zh-CN", "name": "Simplified Chinese", "native": "简体中文"},
         {"code": "fr", "name": "French", "native": "Français"}]


def summary(page, lang, job):
    """runSummary(job) as the page's own scripts compute it, run under node with a stub document."""
    src = "".join((STATIC / name).read_text(encoding="utf-8") for name in (f"{page}.{lang}.js", "langs.js"))
    doc = f"var document = {{documentElement: {{lang: {json.dumps(lang)}}}}};\n"
    code = doc + src + f"\nLANG_LIST = {json.dumps(LANGS)};\nconsole.log(JSON.stringify(runSummary({json.dumps(job)})));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


BASE = {"filename": "化学之树.pdf", "pages_total": 120, "range": "1-120", "source": "fr", "target": "zh-CN",
        "output_mode": "bilingual", "provider": "api", "model": "", "state": "running"}


@node
@pytest.mark.parametrize("page", ["desktop", "web"])
def test_the_summary_names_the_book_languages_and_provider(page):
    s = summary(page, "en", BASE)
    assert s["book"] == "化学之树.pdf · 120 pages"                       # the whole book: no range
    assert s["how"] == "French → Simplified Chinese · bilingual · " + ("Anthropic Claude" if page == "desktop" else "api")


@node
def test_range_preview_target_only_model_and_detected_language():
    s = summary("desktop", "en", dict(BASE, range="5-9"))
    assert s["book"].endswith("· pages 5–9")
    s = summary("desktop", "en", dict(BASE, range="1-3", preview=True))
    assert s["book"].endswith("· preview, pages 1–3")
    s = summary("desktop", "en", dict(BASE, output_mode="target-only", model="qwen-max", provider="qwen"))
    assert s["how"].endswith("· translation only · Qwen (China) qwen-max")
    s = summary("desktop", "en", dict(BASE, source="auto", detected_language="fr"))
    assert s["how"].startswith("French → ")
    s = summary("desktop", "en", dict(BASE, source="auto"))
    assert s["how"].startswith("Auto-detect → ")


@node
def test_chinese_wording_and_old_jobs_with_missing_fields():
    s = summary("desktop", "zh", dict(BASE, range="5-9"))
    assert s["book"] == "化学之树.pdf · 共 120 页 · 第 5–9 页" and "双语对照" in s["how"]
    assert s["how"].startswith("Français → 简体中文")                      # native names on the Chinese page
    s = summary("desktop", "en", {"filename": "old.txt", "state": "done"})   # a job made before these fields existed
    assert s["book"] == "old.txt" and s["how"] == "bilingual"


@node
def test_a_long_file_name_is_kept_whole_for_the_page_to_wrap():
    name = "A very long book title " * 12 + ".pdf"
    assert summary("desktop", "en", dict(BASE, filename=name))["book"].startswith(name)


def test_the_progress_card_has_the_summary_in_every_page_and_language():
    for f in ("desktop.en", "desktop.zh", "web.en", "web.zh"):
        html = (STATIC / f"{f}.html").read_text(encoding="utf-8")
        assert 'id="runinfo"' in html and 'id="run-book"' in html and 'id="run-set"' in html, f
        assert html.index('id="runinfo"') < html.index('id="bar"'), f           # above the progress bar
        js = (STATIC / f"{f}.js").read_text(encoding="utf-8")
        for k in ("sumPages", "sumRange", "sumPreview", "sumBilingual", "sumTargetOnly"):
            assert f"{k}:" in js, (f, k)
    for f in ("desktop.js", "web.js"):
        assert "fillRunInfo(" in (STATIC / f).read_text(encoding="utf-8"), f
    assert "restoreForm(" in (STATIC / "desktop.js").read_text(encoding="utf-8")
    assert ".runinfo" in (STATIC / "ui.css").read_text(encoding="utf-8")


def test_the_job_returns_what_the_summary_needs_and_never_a_key(make_client):
    c = make_client()
    job = upload(c, "b.txt", b"Hello there, this is a short book. " * 40).json()
    key = KEY
    r = c.post(f"/api/jobs/{job['id']}/start", json={"api_key": key, "provider": "api", "model": "claude-haiku-5-5",
                                                    "target": "fr", "output_mode": "target-only"})
    assert r.status_code == 200
    j = wait(c, job["id"])
    assert (j["provider"], j["model"], j["target"], j["output_mode"]) == ("api", "claude-haiku-5-5", "fr", "target-only")
    assert j["range"] and j["pages_total"] >= 1 and "ocr" in j
    assert key not in json.dumps(j) and "api_key" not in j
