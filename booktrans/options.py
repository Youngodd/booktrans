"""What a translation job is asked to do: the settings, their defaults, and their checking.

The command line, the web service and the library all describe a job with the same settings.
They are defined here once, so a new option is added in one place, with its default and its
validation, and the entry points only fill it in.

Not part of it: the objects a run works with (the translating backend, the OCR backend, the
progress callback, the spend meter). They belong to one run, not to the job's description.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import languages


@dataclass(frozen=True)
class JobOptions:
    """The settings of one translate_book run. Validated when created (ValueError)."""

    pages: Optional[str] = None          # page range such as "1-20"; None = the whole book
    redo: Optional[str] = None           # pages to translate again despite the cache
    flat: bool = False                   # PDF input: plain-text pages instead of the original layout
    glossary_file: Optional[Path] = None  # `original=translation` lines that override the glossary
    auto_glossary: bool = True           # find repeated names and fix one rendering for each
    only_cached: bool = False            # spend nothing: build the PDF from the pages already translated
    refresh_glossary: bool = False       # translate again the cached pages whose glossary entries changed
    source: str = "auto"                 # language code of the book, or "auto" (detected)
    target: str = languages.DEFAULT_TARGET  # language code to translate into
    output_mode: str = "bilingual"       # or "target-only"
    state: Optional[Path] = None         # the file the cache, OCR and glossary names are built from

    def __post_init__(self):
        put = object.__setattr__  # frozen: normalise in place
        put(self, "source", languages.check_source(self.source))
        put(self, "target", languages.check_target(self.target))
        languages.check_mode(self.output_mode)
        if self.refresh_glossary and self.only_cached:
            raise ValueError("Re-translating pages and finishing without spending cannot be combined.")
        for name in ("glossary_file", "state"):
            if getattr(self, name):
                put(self, name, Path(getattr(self, name)))
