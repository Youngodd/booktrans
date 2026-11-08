"""The languages the translator offers, and detection of a book's own language.

One list (LANGUAGES) feeds the prompts, the page labels, the CLI, the web API and the
pickers in the web pages (through /api/config). Detection needs no model and no extra
package: the writing system settles most languages, and common words settle the Latin
ones. When it is not sure it says so (None) and the translating model works the source
language out itself.
"""
import re
import unicodedata
from collections import Counter

# code, English name, native name, right-to-left, page label ({n} is the page number)
LANGUAGES = {
    "en": ("English", "English", False, "Page {n}"),
    "zh-CN": ("Simplified Chinese", "简体中文", False, "第 {n} 页"),
    "zh-TW": ("Traditional Chinese", "繁體中文", False, "第 {n} 頁"),
    "ja": ("Japanese", "日本語", False, "{n} ページ"),
    "ko": ("Korean", "한국어", False, "{n}쪽"),
    "es": ("Spanish", "Español", False, "Página {n}"),
    "fr": ("French", "Français", False, "Page {n}"),
    "de": ("German", "Deutsch", False, "Seite {n}"),
    "pt": ("Portuguese", "Português", False, "Página {n}"),
    "ru": ("Russian", "Русский", False, "Страница {n}"),
    "ar": ("Arabic", "العربية", True, "صفحة {n}"),
    "hi": ("Hindi", "हिन्दी", False, "पृष्ठ {n}"),
    "it": ("Italian", "Italiano", False, "Pagina {n}"),
}
DEFAULT_TARGET = "zh-CN"
OUTPUT_MODES = ("bilingual", "target-only")

# Languages whose capitalised mid-sentence words are names, so the automatic glossary of
# repeated names makes sense (German capitalises every noun, the rest have no capitals).
NAME_CAPITALS = {"en", "es", "fr", "pt", "it"}


def check_target(code):
    """The canonical code of a target language; ValueError for one we do not offer."""
    for c in LANGUAGES:
        if c.lower() == str(code).strip().lower():
            return c
    raise ValueError(f"Unsupported target language {code!r} (use one of: {', '.join(LANGUAGES)})")


def check_source(code):
    """`auto` (detect), or the canonical code of a language we know."""
    if not code or str(code).strip().lower() == "auto":
        return "auto"
    return check_target(code)


def check_mode(mode):
    if mode not in OUTPUT_MODES:
        raise ValueError(f"Unsupported output mode {mode!r} (use {' or '.join(OUTPUT_MODES)})")
    return mode


def name(code):
    """English name for the prompts; "auto" reads as a request to work it out."""
    return LANGUAGES[code][0] if code in LANGUAGES else "the source language (identify it yourself)"


def native_name(code):
    return LANGUAGES[code][1] if code in LANGUAGES else "Original"


def is_rtl(code):
    return code in LANGUAGES and LANGUAGES[code][2]


def page_label(code, n):
    fmt = LANGUAGES[code][3] if code in LANGUAGES else "Page {n}"
    return fmt.format(n=n)


def listing():
    """For the pickers: [{code, name, native, rtl}]."""
    return [{"code": c, "name": v[0], "native": v[1], "rtl": v[2]} for c, v in LANGUAGES.items()]


# ---- detection -------------------------------------------------------------------------

_SCRIPTS = (
    ("kana", re.compile(r"[぀-ヿㇰ-ㇿ]")),
    ("hangul", re.compile(r"[가-힯ᄀ-ᇿ]")),
    ("han", re.compile(r"[㐀-䶿一-鿿]")),
    ("cyrillic", re.compile(r"[Ѐ-ӿ]")),
    ("arabic", re.compile(r"[؀-ۿݐ-ݿ]")),
    ("devanagari", re.compile(r"[ऀ-ॿ]")),
    ("latin", re.compile(r"[A-Za-zÀ-ɏ]")),
)
# characters used only in Traditional Chinese, and only in Simplified: they tell the two apart
_TRAD = set("這個們來時學國會對說還從點後開問際體頭實錢門號馬書買賣愛電話車觀歡聽讀寫語麼麽灣"
            "樣機關無與業為產東農習義長嗎應該間總經動當與條憶藝線團圖壓處發變歷變")
_SIMP = set("这个们来时学国会对说还从点后开问际体头实钱门号马书买卖爱电话车观欢听读写语么湾"
            "样机关无与业为产东农习义长吗应该间总经动当条忆艺线团图压处发变历")
# the commonest words of each Latin-script language (none is in another's list)
_WORDS = {
    "en": "the and of to in is that it was for with as his he be on at by this had not are but from or have an they which you were her all she there would their we him been has when who will more no if out so said what up its about into than them can only other new some could time these two may then do first any my now such like our over man me even most made after also did many before must through back years where much your way well down should because each just those people how too little state good very make world still own see men work long get here between both life being under never day same another know while last might us great old year off come since against go came right used take three".split(),
    "es": "el la los las de que y en un una es se no por con para su al lo como más pero sus le ya o este sí porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante ellos e esto mí antes algunos qué unos yo otro otras otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros".split(),
    "fr": "le la les de des du un une et est en que qui dans pour pas sur au avec ce il elle ne se par plus son sa ses mais ou où nous vous ils elles être avoir fait comme tout cette sont aux ont leur leurs aussi même entre sans sous très bien peut dont cet ces quand alors été était fait faire encore autre autres si y mon ma mes ton ta tes".split(),
    "de": "der die das und ist in den von zu mit sich des auf für nicht ein eine als auch es an werden aus er hat dass sie nach wird bei einer um am sind noch wie einem über einen so zum war haben nur oder aber vor zur bis mehr durch man sein wurde sei ich wir ihr dem kann gegen vom können schon wenn habe seine ihre dann unter wir".split(),
    "pt": "o a os as de do da dos das que e em um uma é se não por com para seu sua ao como mais mas foi são ou ele ela também já só pelo pela até isso entre quando muito nos à você tem seus suas quem nas me esse eles estão você tinha foram essa num nem suas meu às minha têm numa pelos elas havia seja qual será nós tenho lhe deles essas esses pelas este fosse dele".split(),
    "it": "il lo la i gli le di del della dei delle che e è un una in per con non si da come più ma ha sono al alla anche ne se ci ho questo questa suo sua loro quando molto tutto tutti nel nella essere fatto stato dove cui perché ancora sempre solo già mi ti lui lei noi voi cosa fra tra senza sulla sul degli era erano ogni ed hanno avere".split(),
}
_WORDSETS = {c: set(w) for c, w in _WORDS.items()}
_LATIN_WORD = re.compile(r"[^\W\d_]+")


def _latin_language(text):
    words = [w.lower() for w in _LATIN_WORD.findall(text)]
    if len(words) < 30:
        return None
    score = {c: sum(1 for w in words if w in ws) / len(words) for c, ws in _WORDSETS.items()}
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    (best, top), (_, second) = ranked[0], ranked[1]
    if top < 0.12 or top < second * 1.25:  # too few common words, or two languages tie
        return None
    return best


def detect_language(texts):
    """The language code of the text, or None when it cannot be told with confidence.

    `texts` is a string or a list of page texts. Every page contributes, so a cover or
    a front-matter page in another language does not decide it.
    """
    text = texts if isinstance(texts, str) else "\n".join(texts)
    text = unicodedata.normalize("NFC", text)[:400_000]
    counts = Counter({k: len(rx.findall(text)) for k, rx in _SCRIPTS})
    total = sum(counts.values())
    if total < 20:
        return None
    # Kana is the mark of Japanese even in a text that is mostly kanji
    if counts["kana"] >= 0.05 * (counts["kana"] + counts["han"]) and counts["kana"] >= 5:
        return "ja"
    if counts["hangul"] > 0.3 * total:
        return "ko"
    if counts["han"] > 0.3 * total:
        trad = sum(1 for ch in text if ch in _TRAD)
        simp = sum(1 for ch in text if ch in _SIMP)
        return "zh-TW" if trad > simp else "zh-CN"
    for script, code in (("cyrillic", "ru"), ("arabic", "ar"), ("devanagari", "hi")):
        if counts[script] > 0.3 * total:
            return code
    if counts["latin"] > 0.6 * total:
        return _latin_language(text)
    return None


def sample_pages(pages, limit=12):
    """Pages spread over the whole book (not just its start), for detection."""
    pages = [p for p in pages if p and p.strip()]
    if len(pages) <= limit:
        return pages
    step = len(pages) / limit
    return [pages[int(k * step)] for k in range(limit)]


def has_words(text):
    """True if the text holds something to translate: two letters, or one CJK character."""
    return bool(re.search(r"[^\W\d_]{2}|[぀-ヿ㐀-鿿가-힯]", text))
