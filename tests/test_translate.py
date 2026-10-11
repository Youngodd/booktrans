import json
from booktrans.translate import translate, translate_all, translate_blocks, load_cache

B = [{"text": "Hello"}, {"text": "World"}]

def test_translate_empty_skips_call(fake):
    assert translate(fake, "  ") == "" and fake.calls == []

def test_blocks_happy_path(fake):
    assert translate_blocks(fake, B) == ["译1", "译2"]
    assert len(fake.calls) == 1

def test_blocks_strips_markdown_bold(fake):
    fake.reply = "[1] **你好**\n[2] 世界"
    assert translate_blocks(fake, B) == ["你好", "世界"]

def test_blocks_retry_then_success(fake):
    replies = iter(["[1] only one", "[1] a\n[2] b"])
    fake.reply = lambda u: next(replies)
    assert translate_blocks(fake, B) == ["a", "b"]
    assert len(fake.calls) == 2

def test_blocks_fallback_one_by_one(fake):
    fake.reply = lambda u: "garbage" if "[1]" in u else "单"
    assert translate_blocks(fake, B) == ["单", "单"]

def test_blocks_multiline_block(fake):
    fake.reply = "[1] line a\nline b\n[2] c"
    assert translate_blocks(fake, B) == ["line a\nline b", "c"]

def test_blocks_context_in_prompt(fake):
    translate_blocks(fake, B, ("PREV", "NEXT"))
    assert "PREV" in fake.calls[0] and "NEXT" in fake.calls[0]

def test_translate_all_caches_and_resumes(fake, tmp_path):
    cp = tmp_path / "c.json"; cache = {}
    t = translate_all(fake, [0, 1], ["a", "b"], {}, {}, cache, cp)
    assert t == ["译:a", "译:b"] and json.loads(cp.read_text()) == cache
    n = len(fake.calls)
    translate_all(fake, [0, 1], ["a", "b"], {}, {}, load_cache(cp), cp)
    assert len(fake.calls) == n

def test_translate_all_redo(fake, tmp_path):
    cp = tmp_path / "c.json"; cache = {"1": "old"}
    assert translate_all(fake, [1], ["b"], {}, {}, cache, cp, redo={1}) == ["译:b"]

def test_translate_all_layout_page(fake, tmp_path):
    cp = tmp_path / "c.json"; cache = {}
    t = translate_all(fake, [4], ["x"], {0: B}, {0: ("", "")}, cache, cp)
    assert t == [""] and cache["L4"] == ["译1", "译2"]

def test_layout_cache_length_mismatch_retranslates(fake, tmp_path):
    cp = tmp_path / "c.json"; cache = {"L4": ["only one"]}
    translate_all(fake, [4], ["x"], {0: B}, {0: ("", "")}, cache, cp)
    assert cache["L4"] == ["译1", "译2"]
