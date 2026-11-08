# Mac end-to-end run, 2026-11-08

Build under test: `desktop-app` branch at 7669aea plus uncommitted docs/packaging edits; run from source
(`.venv/bin/python`, Python 3.9.6), not an installer build. macOS 27.0, arm64. Run by Claude Code.
No real provider was called (fake backend), no real API key was used, and the real Keychain entry
`BookTranslator` was not touched (its creation/modification timestamps were identical before and after; a
file-backed keyring stand-in, `tests/e2e/mac/fakekr.py`, was used for every key test). No source file was changed.

How: `tests/e2e/mac/shim.py` is the real desktop sidecar with only the fake backend swapped for one that can be
slowed, failed on demand, or reject a marker key; retry waits were shortened from 5/20/60 s to 0.2 s. The
per-call cost of the fake backend is ¥1, so the default ¥10 limit stops a 12-page book (that is the spend guard
working; the tests pass `spend_limit` explicitly).

## Results

| Step | Plan ID | Result | Evidence |
| --- | --- | --- | --- |
| 1a | pytest | pass | 170 passed in 9.6 s (plan said about 132; `tests/test_web.py` unchanged) |
| 1b | smoke_test.py | pass | `SMOKE OK`, but only with `NO_PROXY` set (see bug 1) |
| 1c | ui_check.py | pass | `UI CHECK OK ...`; needs `PYTHONPATH=.` when run from the repo (see note 1) |
| 2a | A3 / F32 window opens | pass | Window title "Book Translator" seen: first (cold) launch 18.1 s, second launch 0.8 s. The 15 s target is missed on a cold first start only. `app-window.png` |
| 2b | A4 close leaves nothing | pass | Red close button clicked: shell exited, sidecar gone within 2 s |
| 2c | A5 kill main, sidecar ends | **FAIL on macOS** | `kill -9` of the shell left the sidecar running (bug 2); `packaging/orphan_test.py` reports `ORPHAN TEST FAILED`. The guard is a Windows job object, so this is expected on Mac; Windows still needs a run |
| 3 / B7 | first run, no key | pass | `has_key` false at first run |
| 3 / B10 | rejected key not kept | pass | 401 "The provider rejected this key."; nothing stored |
| 3 / B11 | network error differs from rejected | pass | 502 "Could not reach the provider. Check your network." |
| 3 / B12 | saved key survives restart | pass | New sidecar+shell process: `has_key` true, provider `api`, hint `…0000`; `use_stored_key` handed it over |
| 3 / B13 | key in no file | pass | `sk-test-0000` in no file under the data folder, including `sidecar.log`, `prefs.json`, every `job.json`; not in `/api/config` or `/api/jobs`. (Real Credential Manager / Keychain entry: not checked here) |
| 3 / B14 | delete key | pass | `has_key` false in store and in the running sidecar; deleting twice is harmless |
| 3 | empty key | pass | 400 "请输入 key。 Enter a key." |
| 4 / C16, T2 | PDF translates | pass | 12 pages -> 24; page 1 original, page 2 Chinese text extractable (`译1 译2`) |
| 4 / C18, T2 | EPUB, TXT | pass | both done, Chinese text present |
| 4 / C16 | page range, preview | pass | `3-5` -> 6 pages starting at page 3; `50-60` rejected 400; preview -> 3 pages x 2 |
| 4 / C17 | name review | pass | draft produced 3 names; the edited rendering `阿尔法泽塔XYZ` appears in the translation prompts |
| 4 / C20, C1, C2 | Chinese name and path | pass | `测试/书籍/化学之树.pdf`: name kept, download name `化学之树_bilingual.pdf`; data folder path also contained Chinese |
| 4 / C21, T4 | cancel, continue | pass | Paused after 4 calls, no calls while paused; Continue finished with 12 calls total vs 12 for a clean run (no page redone) |
| 4 / C22, T5 | kill mid-run | pass | `kill -9` of the sidecar mid-run, relaunch: job shown `paused`, Continue -> 200 (no 409), finished |
| 4 / C26, T6 | delete book | pass | job folder removed, GET -> 404 |
| 5 | spend guard | pass | limit ¥3 -> `needs_decision` at ¥3.00 with an estimate for the rest; raise -> done, 24 pages; finish-partial -> done, `partial` true, 6 pages; stop -> `paused`; starting with a limit under what is spent -> 400 |
| 6 / C23, E2 | provider failure | pass | Simulated outage -> `failed` with "The provider returned an error. Press Continue to retry ..."; after it ended, Continue -> done. This is a simulated backend error, not a real network cutoff |
| 7 | UI eyes | partly | Window screenshot taken (`app-window.png`, Chinese UI renders, themes button present). Native Save dialog, Show in folder, PDF viewers (C24, C25): **needs a person** |

Not run: needs Windows (installer, SmartScreen, no-admin install, Start menu, Credential Manager, WebView2,
uninstall, upgrade, antivirus, ARM64 VM: A1, A2, A6, B13 (Windows part), E29-E31). Not run: needs real
providers or hardware (B8 locale default on a Chinese Windows, B9 key pages in a browser, C19 OCR, C23 real
network cutoff, D27-D28 400-page memory). These remain open.

## Bugs found (reported, not fixed)

1. **A proxy environment breaks the shell's key save.** With `HTTP_PROXY=http://127.0.0.1:13128` set (no
   `NO_PROXY`), `python -m booktrans.desktop.shell --headless-check` dies with `json.decoder.JSONDecodeError`
   in `Api._push`: the shell's `httpx.Client` (`Sidecar.start`, `shell.py`) honours proxy variables, so its
   calls to `127.0.0.1` go to the proxy, which answers with an HTML 500. `packaging/smoke_test.py` fails the
   same way (`/api/config` assertion). On Windows httpx also reads the system proxy, so a user with a system
   proxy is exposed. Reproduce: `HTTP_PROXY=http://127.0.0.1:1 .venv/bin/python -m booktrans.desktop.shell --headless-check`
   (any listening proxy; mine was a sandbox tinyproxy). Likely fix: `httpx.Client(..., trust_env=False)`
   for the sidecar connection. The page in the window is a separate matter (the web view's own proxy rules)
   and was not tested.
2. **The sidecar outlives a killed shell on macOS.** `kill -9 <shell pid>` leaves `python -m booktrans.desktop`
   running (orphan_test fails). Only Windows has the kill-on-close job object (`_kill_with_parent_on_windows`).
   Matters for the Mac development run only.
3. **Low: the per-launch API token is written to `sidecar.log`** (the `BOOKTRANS_READY port=... token=...` line
   goes to the log file). It is valid only for that launch on localhost, but the log is kept and may be shared in
   bug reports. The API key itself is never logged.

Notes: (1) `packaging/ui_check.py` fails with `ModuleNotFoundError: No module named 'booktrans'` unless
`PYTHONPATH=.` is set (CI presumably installs the package). (2) The first cold start took 18 s; one sample
only, not a reliable figure. (3) A first full-desktop screenshot was discarded because it showed unrelated
private windows; only the region capture of the app window is kept.

## Files

`e2e-results.json` raw per-test results; `tests/e2e/mac/` the scripts used (`e2e.py` steps 4-6, `keyflow.py` step 3,
`window.py` / `window2.py` step 2, `shim.py`, `fakekr.py`); `app-window.png` the app window.
