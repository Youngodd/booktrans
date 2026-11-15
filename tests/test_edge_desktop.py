"""Edge cases of the desktop shell's saved model choices and the Qwen model list."""
import json
import threading

import pytest

from booktrans.backends import catalog
from booktrans.desktop import shell


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOKTRANS_DATA", str(tmp_path))
    return shell.Api(None)


@pytest.mark.parametrize("body", ["", "{", "null", "[]", '"x"', "5", '{"models": null}', '{"models": []}',
                                  '{"models": "x"}', '{"models": {"qwen": null}}', '{"models": {"qwen": []}}',
                                  '{"models": {"qwen": {"model": 5}}}', '{"models": {"qwen": {"model": "bad id!"}}}',
                                  '{"models": {"1": {"model": "ok"}}}', "\x00\x01\x02"])
def test_a_damaged_preferences_file_reads_as_nothing_chosen(api, tmp_path, body):
    (tmp_path / "prefs.json").write_text(body, encoding="utf-8", errors="ignore")
    got = api.get_models()
    assert isinstance(got, dict) and all(m.get("model", "") == "" or m["model"].replace(".", "").replace("-", "").isalnum()
                                         for m in got.values())
    assert api.set_models("qwen", "qwen3.8-max", "")["ok"]  # and it can be written over
    assert api.get_models()["qwen"]["model"] == "qwen3.8-max"


@pytest.mark.parametrize("model", ["bad id!", "a b", "../x", "x" * 101, "名前", "", "-lead", ".lead", "a;b", "a\nb", "<x>"])
def test_unsafe_model_ids_are_refused_or_empty_means_the_default(api, model):
    ok = api.set_models("qwen", model, "")["ok"]
    assert ok is (model == "")


def test_the_longest_allowed_model_id_is_kept(api):
    assert api.set_models("qwen", "m" * 100, "")["ok"]
    assert api.get_models()["qwen"]["model"] == "m" * 100


@pytest.mark.parametrize("provider", [None, 5, ["qwen"], {"a": 1}])
def test_a_provider_that_is_not_a_name_is_refused(api, provider):
    assert api.set_models(provider, "qwen3.7-plus", "")["ok"] is False


def test_a_provider_name_that_is_unknown_is_stored_harmlessly(api):
    assert api.set_models("not-a-provider", "some-model", "")["ok"]
    assert api.get_models()["not-a-provider"]["model"] == "some-model"


def test_choices_saved_from_several_threads_at_once_leave_a_valid_file(api, tmp_path):
    def save(n):
        api.set_models(f"p{n}", f"model-{n}", "")
    threads = [threading.Thread(target=save, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    data = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))["models"]
    assert len(data) == 20 and not list(tmp_path.glob("*.tmp"))


def test_an_old_saved_qwen_name_still_works_as_a_typed_model(api):
    """Names like qwen-max, saved before the list was renumbered, are not dropped."""
    assert api.set_models("qwen", "qwen-max", "qwen-vl-max")["ok"]
    assert api.get_models()["qwen"] == {"model": "qwen-max", "ocr_model": "qwen-vl-max"}


@pytest.mark.parametrize("provider", ["qwen", "qwen-intl"])
def test_the_qwen_lists_carry_version_numbers_and_the_default_comes_first(provider):
    cfg = catalog()[provider]
    assert cfg["models"][0] == cfg["model"] and cfg["vision_models"][0] == cfg["vision"]
    for name in cfg["models"] + cfg["vision_models"]:
        assert name.startswith("qwen") and any(ch.isdigit() for ch in name), name  # no bare qwen-plus / qwen-max
    assert len(set(cfg["models"])) == len(cfg["models"])
