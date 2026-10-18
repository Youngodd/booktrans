# Desktop app plan

Status: draft; M1 partly built on this branch (see "Progress"). Implements [ADR 0002](adr/0002-develop-desktop-app.md); resolves its TODOs once approved.
The phone version (mini program and hosted web service) stays as tagged in `miniprogram-v1`
and is maintained on `maint/miniprogram`.

## Goal

A desktop app where the user pastes their own API key once, and the book is translated on their own
computer. No server of ours, no key or book leaves the machine except to the chosen provider.

## Decisions so far

| Question | Decision |
| --- | --- |
| First platform | Windows. macOS later (ADR 0002 says both; Windows ships first). |
| Phone version | Keep, minimal upkeep. |
| Providers | Anthropic (`api`), Qwen (`qwen`, `qwen-intl`), DeepSeek (`deepseek`). `claude-cli` hidden. |
| Engine | The existing Python package, unchanged where possible. |
| License | AGPL-3.0, because PyMuPDF is bundled ([ADR 0003](adr/0003-license-desktop-app-under-agpl.md)). |
| Shell | Open. Tauri vs pywebview, decided by the M0 spike. |

## What exists and what changes

| Part | Plan |
| --- | --- |
| `pipeline.translate_book`, `readers`, `layout`, `writer`, `glossary`, `translate`, `backends/` | Reuse. `make_backend(api_key=...)` already takes a key. Add a cancel hook (see below). |
| `web/app.py` job API | Reuse behind a desktop mode (see below). |
| `web/static/index.html` (380 lines) | Adapt: remove login, email and HTTP key warning; add first-run, settings, save dialog. Not yet audited line by line. |
| `web/auth.py`, `mailer.py`, `wxcloud.py` | Not used by the desktop build. |
| `miniprogram/` | Untouched. |

### Desktop mode must be additive

Changes to `web/` on this branch must not change the hosted service. Put desktop behaviour behind
`create_app(desktop=True)` in a new entry point (`booktrans/desktop/`), and keep `tests/test_web.py`
passing unchanged.

Desktop mode differences:
- No login. Bind to `127.0.0.1` on a random port; require a per-launch token header.
- No upload cap, no page cap, **no 24-hour cleanup**. Jobs and resume caches live until the user deletes them.
- Data folder under `%APPDATA%` (Windows).
- Original file name kept for the save dialog (`SAFE_NAME` currently turns Chinese names into `____`).
- On startup, jobs left in `queued` / `running` are reset to an interrupted state, so Start does not fail
  with 409 after a closed app.
- Requests carry no `api_key` (see key flow).

## API key flow

1. First run: choose provider (and region for Qwen: domestic and international keys differ), paste key.
2. Validate with a 1-token request. `AuthError` means "key rejected"; network errors are reported
   separately. Save only after it passes.
3. Store in the OS credential store (Windows Credential Manager). Never in a file, never logged;
   crash logs redact keys.
4. The shell gives the key to the sidecar once per session (stdin or a local endpoint, not the page's
   JavaScript). Start and glossary requests then omit `api_key`.
5. Settings: replace or delete the key, switch provider, pick model and OCR model.
6. The app explains how to get a key for each provider (ADR 0002 risk).

## Architecture

```
Shell (Tauri or pywebview)         Python sidecar (PyInstaller, onedir)
┌─────────────────────┐  spawn    ┌─────────────────────────────┐
│ WebView: adapted UI │ ────────► │ FastAPI on 127.0.0.1:<random>│
│ credential store    │  token    │ booktrans.pipeline           │
│ file dialogs        │ ◄──────── │ data dir in %APPDATA%        │
└─────────────────────┘ HTTP+token└──────────────┬──────────────┘
                                                  │ HTTPS, key only to the chosen provider
                                                  ▼ Anthropic / DashScope / DeepSeek
```

The sidecar must not outlive the app (on Windows use a job object or equivalent).

## Bundle size

Measured in the current venv (`site-packages` about 300 MB uncompressed, before PyInstaller):

| Package | Size | Note |
| --- | --- | --- |
| `cv2` (OpenCV) | 120 MB | Used by one function: `figures.ink_layer` (scanned pages) |
| `pymupdf` | 50 MB | Core |
| `numpy` | 21 MB | Needed by OpenCV |
| `lxml` | 20 MB | EPUB parsing |
| `PIL`, `fontTools`, `openai`, `anthropic`, `reportlab`, others | about 50 MB | Core |

Expectation: roughly 100-150 MB installed after PyInstaller and `--exclude-module` pruning. This is a
guess until M0 measures it.

Options for OpenCV: (1) keep it for the MVP (recommended; no regression risk to tuned scan output);
(2) later, rewrite `ink_layer` with NumPy and PIL to save about 120 MB, using the `ChemicalTree` pages
as the regression test; (3) download it on first use of scanned-book mode (more machinery). Not an MVP blocker.

## Shell choice (decided after M0)

| | Tauri + sidecar | pywebview + PyInstaller |
| --- | --- | --- |
| Extra toolchain | Rust | None |
| Credential store | Rust `keyring` crate | Python `keyring` (same Windows store) |
| Installer, updater | Built in, but every update re-downloads the whole bundle | Hand-built |
| Sidecar lifecycle | Needs care (orphan processes) | One process |
| Native feel | Better | Basic |

Both are viable. The Python bundle dominates size either way, so shell size is not a deciding factor.
The deciding factors are the updater, the maintenance load of Rust for a solo maintainer, and how the
M0 spike goes.

## Features

MVP:
- Drag and drop PDF, EPUB, TXT; page range; 3-page preview; glossary review.
- OCR toggle (disabled for DeepSeek, which has no vision).
- Progress; Pause/Cancel (needs a cancel hook in the pipeline, e.g. `progress` raising a cancel exception);
  Continue after interruption (the cache already supports it).
- Per-provider cost estimate in the right currency, and a spend guard so retries cannot run up a bill
  on the user's key.
- Save PDF where the user chooses; open folder.
- Proxy setting (desktop apps do not inherit shell proxy variables; many users need one).
- Simplified Chinese and English UI (to be confirmed).

Deferred: auto-update, macOS build, job history list, batch queue, phone-as-remote, `claude-cli`.

## Milestones

Effort figures are guesses until M0 is done.

| # | Milestone | Rough effort |
| --- | --- | --- |
| M0 | Spike: PyInstaller bundle of the engine on Windows; translate a sample book (text PDF, scanned PDF, EPUB); check Chinese rendering from `layout.py` (it uses `font-family: sans-serif` in PyMuPDF HTML) and `multiprocessing.freeze_support()` with worker processes; measure size; try both shells; check bundled dependency licenses for AGPL compatibility (`docs/THIRD_PARTY.md`). | 2-3 days |
| M1 | Desktop mode in `web/` (section above), cancel hook, key endpoint, per-provider estimate. Existing tests pass. | 3-4 days |
| M2 | Shell: spawn and stop the sidecar, credential store, file dialogs, first-run and settings screens. | 4-6 days |
| M3 | CI build on a Windows runner producing an installer; smoke test (launch, fake backend, translate 2 pages, check PDF). | 2-3 days |
| M4 | Signing, clean-VM install test, update channel, download location (GitHub Releases plus a mirror reachable from mainland China). | 2-4 days of work, plus waiting on a certificate |

Order: M0, then M1-M4 in sequence. Each step is testable on its own.

## Testing

- Reuse `tests/` (fake backend, no API calls); `test_web.py` must stay green.
- Add desktop-mode tests: token required, no cleanup, stale-job reset, key never in responses or logs.
- GUI smoke test in CI as in M3.
- Manual: clean Windows VM install, Chinese path and file names, a 400-page scan for memory.

## Risks

- **License.** PyMuPDF is AGPL (or a paid Artifex license) and this repo is MIT. Distributing a binary
  that bundles it carries obligations. Decided in ADR 0003: ship under AGPL-3.0 with public
  source. Remaining work: swap `LICENSE` before release, About screen with source link, keep PyMuPDF
  producer metadata in PDFs, third-party notices. Revisit if a closed-source or paid product is wanted.
- **Signing.** Unsigned installers trigger SmartScreen warnings. Options: Azure Trusted Signing or an
  OV/EV certificate (cost to be confirmed).
- **Building for Windows from a Mac.** CI covers builds; hands-on testing needs a Windows VM or machine.
- **Frozen multiprocessing.** Worker processes under PyInstaller on Windows are a likely M0 failure.
- **Antivirus false positives.** Prefer onedir builds; signing helps.
- **Long books.** Memory use of `layout.py` and OpenCV on 400-page scans; cap concurrency.
- **Rate limits and failures.** Retries exist; add a clear paused state with Continue.
- **Reachability.** Anthropic is not reachable from mainland China without a proxy; consider a default
  provider by system locale.
- **Copyright.** See `LEGAL_DISCUSSION.md`; running locally moves the act to the user, but the app
  should say so.
- **Privacy.** Book text goes to the chosen provider; say so on first run. No telemetry.

## Open questions

1. Contributions: ask contributors for a DCO or CLA so relicensing stays possible?
2. Signing: willing to pay for a certificate?
3. Distribution: GitHub Releases only, or also a mainland mirror?
4. UI language: Chinese only, or Chinese and English?
5. Default provider for Chinese-language systems.
6. Update ADR 0002's TODOs after M0 (platforms, stack, update mechanism, hosting).

## Progress

M1 (desktop mode in `web/`), done on the `desktop-app` branch:
- [x] `create_app(desktop=True, token=...)`: per-launch token header on `/api/*`, no upload or page cap,
      no age cleanup, original file names kept, stale `queued`/`running` jobs reset to `paused`.
- [x] Cancel hook: `pipeline.Cancelled`; `POST /api/jobs/{id}/cancel` makes the worker stop at the next
      progress call; the job becomes `paused` and Start continues from the cache.
- [x] Key endpoint: `PUT/DELETE /api/key` (1-token validation; 401 for a rejected key, 502 for a network
      error; key kept in memory only). Start and glossary requests may omit `api_key`.
- [x] Entry point `python -m booktrans.desktop` (127.0.0.1, random port, prints `BOOKTRANS_READY port= token=`).
- [x] Tests: `tests/test_desktop.py`; `tests/test_web.py` unchanged.
- [ ] Per-provider cost estimate: only the Anthropic figure is measured; Qwen/DeepSeek per-page costs
      need measuring before they are shown. Spend guard not started.
- [ ] Adapting `web/static/index.html` (first run, settings, save dialog) belongs with M2.

Choices made without asking: the sidecar runs jobs in a thread (`ThreadPoolExecutor(1)`), not worker
processes, which sidesteps frozen multiprocessing (an M0 risk) and serialises jobs; cancel uses a flag
file so it also works with a process pool. The token protects `/api/*` only; `/` is the static page.

Not started, and why: M0 needs a Windows machine; M2 depends on the M0 shell choice; M3 and M4 need a
Windows runner and (for M4) a certificate and a decision on paying for one.
