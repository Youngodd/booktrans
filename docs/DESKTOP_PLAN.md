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
| Shell | pywebview for the MVP (chosen in [SHELL_COMPARISON.md](SHELL_COMPARISON.md); Windows CI confirmed the key flow, job-object cleanup and the build). Tauri stays possible: the shell only talks HTTP to the sidecar. |

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
- ~~Proxy setting~~ Dropped: the app makes direct requests and has no proxy setting.
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
- **Reachability.** Anthropic is not reachable from mainland China, and the app has no proxy setting; the default
  provider follows the system locale (Qwen on a Chinese-language system).
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
      need measuring before they are shown. (Now done as estimates, see "Spend guard" below.)
- [ ] Adapting `web/static/index.html` (first run, settings, save dialog) belongs with M2.

Choices made without asking: the sidecar runs jobs in a thread (`ThreadPoolExecutor(1)`), not worker
processes, which sidesteps frozen multiprocessing (an M0 risk) and serialises jobs; cancel uses a flag
file so it also works with a process pool. The token protects `/api/*` only; `/` is the static page.

Not started, and why: M0 needs a Windows machine; M2 depends on the M0 shell choice; M3 and M4 need a
Windows runner and (for M4) a certificate and a decision on paying for one.

### M0/M3 groundwork: Windows CI

- [x] `.github/workflows/desktop-windows.yml` (runs on push to `desktop-app` or by hand): pytest on Windows,
      PyInstaller onedir build of the sidecar, smoke test of the frozen build, bundle size and largest
      folders in the job summary, bundle uploaded as an artifact. **Not yet run on GitHub.**
- [x] `packaging/sidecar_entry.py` (PyInstaller entry, calls `freeze_support`) and `packaging/smoke_test.py`
      (Chinese data folder and file name, fake backend via `BOOKTRANS_FAKE_BACKEND=1`, checks the output
      PDF contains Chinese text).
- Checked locally on macOS only: the same build and smoke test pass. The bundle is 353 MB there, well above
  the 100-150 MB guess above; the Windows number will come from CI.

### Shell comparison (M0)

- [x] pywebview prototype `booktrans/desktop/shell.py` with key flow, credential store and Windows job object.
- [x] Written comparison and recommendation: [SHELL_COMPARISON.md](SHELL_COMPARISON.md). Tauri was assessed from
      documentation only; no Tauri build was made.
- [x] Windows CI (run on `2b0cdcf`, all steps green): the key flow through the real Windows credential store,
      the orphan test (sidecar ended when the shell was killed) and the PyInstaller build of the shell passed.
      The shell bundle size is in that run's job summary; not yet copied here.

### M2: shell and screens (in progress)

Built on this branch:
- [x] `web/static/desktop.html`, served as `/` in desktop mode (the hosted page is untouched): first-run key screen
      with provider and Qwen region, how-to-get-a-key links per provider, privacy and copyright note; Settings
      (replace or delete the key, switch provider); optional name review before translating; progress with
      Cancel, Pause state and Continue; save dialog and "show in folder"; About with the AGPL source link.
      The page sends the per-launch token on every call and never stores or reads the key.
- [x] Desktop API: `GET /api/jobs` (the page reopens the newest book). Shell: `reveal`, `open_url` (allow-list).
- [x] `packaging/ui_check.py` drives the real window on macOS: first run, key saved, book reopened, name review,
      translated. Passes. Not run in CI (needs a desktop session).
- [x] Proxy setting: built, then removed (the app makes direct requests; `/api/proxy` and the shell's proxy storage are gone).
- [x] Default provider by system language: a `zh-CN`/`zh` system starts on Qwen (China), others on Anthropic
      (open question 5, decided).
- [x] UI language: the page keeps Chinese and English together (open question 4, decided: acceptable).
- [ ] Not done: model and OCR model pickers, per-provider cost figures, spend guard, native save dialog and
      "show in folder" (needs a person at the screen), Windows window check.

### M3: installer (green on Windows CI, commit `64e8416`)

- [x] One program instead of two: `BookTranslator.exe` opens the window; `BookTranslator.exe --sidecar` runs the
      local server (the shell starts a copy of itself). Halves the bundle; the shell finds the server through a
      `--ready-file` (a windowed program has no stdout) and logs to `%APPDATA%\BookTranslator\sidecar.log`.
- [x] `packaging/installer.iss` (Inno Setup): per-user install, no admin rights, Start menu entry, optional desktop
      shortcut, uninstaller; user data is kept on uninstall.
- [x] CI (`desktop-windows.yml`): build the app, smoke-test the frozen app, shell key flow and orphan check against
      it, build the installer, then `packaging/install_check.py`: silent install into a folder with Chinese
      characters, smoke test of the installed app, launch the window (warning only if it fails), uninstall and
      check nothing is left. The installer is uploaded as an artifact.
- Checked on macOS only: the frozen single program passes the smoke test and works as the shell's sidecar.
- Deviations: the installer is English only. WebView2 is assumed present (Windows 10 2018+ and 11).

M3 result on the Windows runner: tests, frozen-app smoke test, shell key flow, orphan check, installer build, silent
install into a folder with Chinese characters, smoke test of the installed app, window launch (no warning raised, so
the window process stayed up and started its sidecar) and uninstall all passed. The installer is 87 MB (the plan's
guess was 100-150 MB installed); the frozen bundle is 257 MB uncompressed. One earlier run failed the frozen-app smoke
test for an unknown reason and passed on the next run with no code change, so it may be intermittent.
Not covered by CI: a real window being used (clicks, dialogs), a clean machine without WebView2, SmartScreen (M4).

### License (ADR 0003): done on this branch

- [x] `LICENSE` replaced with the official AGPL-3.0 text (downloaded from gnu.org, 661 lines); README updated.
- [x] `docs/THIRD_PARTY.md` (generated by `packaging/third_party.py`): no conflicting license found in package
      metadata; binary components inside wheels and the Windows-only packages are listed as not yet verified.
- [x] The installer shows the license page and installs `LICENSE` and the third-party list next to the app.
- [x] About screen with license and source link (M2). PyMuPDF producer metadata is not touched by our code.
- [ ] Still open: contributor DCO/CLA (open question 1), the unverified items in `THIRD_PARTY.md`.

### Spend guard and cost estimates (done)

Decision (owner): every book gets a default limit of **¥10** in total; when a call would take the spend over it, stop,
keep the translated pages in the cache, and ask the user what to do. No spending on signing certificates.
- [x] `booktrans/spend.py`: `Meter` counts every call through a wrapper (translation, retries, glossary, OCR) and
      checks before each call that its estimated cost still fits; `SpendLimitReached` is not a `BackendError`, so
      retries and the glossary cannot swallow it. The total is kept in `<output>.spend.json`, so the limit is per book
      across runs. Limit 0 or none = count but never stop; never switched on or off silently.
- [x] Stop behaviour: finished pages are already in the cache; the glossary names already found are saved.
      Choices: raise the limit and continue (resumes without paying again), finish with the translated pages
      (`only_cached`: builds the PDF from cached pages, makes no call), or stop (job becomes `paused`).
- [x] CLI: `--max-spend YUAN` (default 10, 0 = none); on the limit it asks interactively, or exits with code 3 when
      not interactive; `--finish-partial` builds the PDF from the cached pages.
- [x] Web/desktop: job state `needs_decision` with `spent_cny`, `spend_limit`, `est_rest_cny`; `spend_limit` and
      `only_cached` in the start request; `/api/config` gives `default_spend_limit` and `est_cny_per_page`.
      **Desktop default is ¥10; the hosted service keeps the guard off unless a request sets a limit**, because the
      hosted page and the mini program have no screen for the decision.
- [x] Desktop page: limit field, estimate in yuan for every provider, decision panel (raise / finish / stop).
- [x] Tests: `tests/test_spend.py` and the spend tests in `tests/test_desktop.py` (under the limit, over the limit,
      resume without re-paying, retries counted, no limit, finish with nothing spent, CLI paths, hosted default off);
      `packaging/ui_check.py` drives the stop and "finish" in a real window.

**Caveats.** The prices in `spend.py` are **unverified estimates** (only the Anthropic cost per page, about US$0.017,
was measured); check each provider's price page before relying on the guard. The check before a call uses a rough size
estimate, so a call can still cost somewhat more or less than predicted; the guard stops when the *estimated* next call
would pass the limit. A page that is half translated when the limit hits is paid for but not saved (one page at most).

### Signing (M4): deferred, no money spent

Owner decision: do not spend money on certificates. Unsigned installers show a Windows SmartScreen warning ("unknown
publisher"; the user clicks More info, Run anyway) and some antivirus products may flag them. Free alternatives to
consider later: tell users how to bypass the warning in the README, publish SHA-256 checksums next to the download,
or apply to a free signing programme for open-source projects if one is available (not verified). The update channel
and download hosting (GitHub Releases) need no payment but are not built.

### CI status after the spend guard (commit `8d4fc13`, all steps green)

Windows CI passes with the AGPL license page in the installer, the spend guard and the latest desktop page: 133 tests,
frozen-app smoke test, shell key flow, orphan check, installer build (86 MB), silent install into a folder with Chinese
characters, smoke test of the installed app, window launch (no warning) and uninstall.

Found on the way: the unpinned latest PyMuPDF (newer than 1.26.5) loads an optional layout feature on import whose data
files are not in the PyInstaller bundle, so the frozen app failed at the first book ("Something went wrong"). This also
explains the earlier one-off smoke failure. Fixes: `requirements.txt` pins `pymupdf==1.26.5` (re-test before raising it),
unexpected job failures now log their traceback (key blanked) to `sidecar.log`, and CI prints package versions.
Other dependencies are still unpinned; the same kind of break could come from any of them.
