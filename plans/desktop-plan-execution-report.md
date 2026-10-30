# Execution Report: Desktop app plan

Plan: `docs/DESKTOP_PLAN.md`. Updated 2026-10-26 (first written 2026-10-18).

## Summary
Partial, well advanced. M0 (mostly), M1, M2 and M3 are built and green on Windows CI up to commit `64e8416`;
the AGPL swap, manual test checklist and spend guard are committed locally and not yet run on CI. M4 is deferred
by decision (no spending on signing). Remaining items need a person on Windows or a decision.

## Step results
| Step | Status | Evidence |
| --- | --- | --- |
| M0 spike: Windows bundle, Chinese rendering, shell comparison | Mostly done | CI smoke test with Chinese paths; `docs/SHELL_COMPARISON.md`. Not done: scanned-PDF and EPUB samples, 400-page memory test |
| M1 desktop mode, cancel, key endpoints (the proxy endpoint was later removed) | Done | `tests/test_desktop.py` |
| M2 shell and screens | Done on macOS | `packaging/ui_check.py` drives the real window; not used by a person on Windows |
| M3 installer, CI | Done, green on Windows (run for `64e8416`) | 87 MB installer; silent install into a Chinese-named folder, smoke test, uninstall |
| License to AGPL-3.0, third-party list | Done, green on CI | `LICENSE` (official text), `docs/THIRD_PARTY.md`; binary components inside wheels not verified |
| Spend guard (default ¥10 per book) | Done, green on CI | `booktrans/spend.py`, `tests/test_spend.py`, desktop tests, `ui_check.py` |
| Per-provider cost estimate | Done as estimates | Qwen and DeepSeek rates unverified |
| M4 signing, updates, hosting | Deferred | Owner decision: no money for certificates |
| Model and OCR model pickers | Done on macOS | `tests/test_desktop.py` (default, custom reach `make_backend`, invalid id 400, OCR refused without vision, approximate price, per-provider prefs); `packaging/ui_check.py` selects both in the real window, checks they are restored and sent. Curated model ids other than the repo defaults are from the model list in this session; not checked against provider docs. Spend guard prices any model at the provider rate |
| Manual testing on Windows | Not done | `docs/MANUAL_TEST.md` |

## Deviations
- Sidecar runs jobs in one thread (no worker processes); cancel is a flag file.
- One program (`BookTranslator.exe --sidecar`) instead of two bundles.
- The spend guard defaults to ¥10 in the desktop app and CLI but is off in the hosted service unless a request sets a
  limit, because the hosted page and the mini program cannot show the decision.
- The spend check uses an estimate of the next call's size, so it can be off by part of one call; a page half
  translated at the limit is paid for but not saved.

## Test results
- `.venv/bin/python -m pytest -q`: 132 passed (macOS, Python 3.9), including 19 in `tests/test_spend.py`.
- `packaging/ui_check.py`: passes (first run, key, book reopen, name review, spend stop, finish with translated pages).
- `packaging/smoke_test.py` against the dev sidecar: passes.
- Windows CI: green for `8d4fc13` (everything up to the spend guard). The earlier intermittent smoke failure was a newer PyMuPDF whose optional layout data files are missing from the bundle; fixed by pinning `pymupdf==1.26.5`.
- No real provider was called at any point.

## Audit findings
- Prices in `spend.py` are unverified; the guard is only as good as those numbers. Stated in the code, plan and UI.
- Other dependencies are unpinned and could break the frozen build the same way PyMuPDF did.
- Hosted-service behaviour is unchanged except that `api_key` is optional in the request models (400, not 422).
- Open: the intermittent smoke failure; wheel-internal licenses; contributor DCO/CLA.

## Definition of done
Per milestone, as in the plan: M1 to M3 met (CI evidence above). Spend guard: the five listed behaviours are tested
(under limit, over limit with cache saved and spend reported, resume without re-paying, retries counted, no limit).

## Follow-ups
Push so CI checks the installer and everything since `64e8416`; run `docs/MANUAL_TEST.md` on Windows; verify provider
prices; model and OCR pickers; update channel and README note about SmartScreen.
