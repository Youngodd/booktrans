# Windows VM test plan (UTM, Windows 11)

Builds on [MANUAL_TEST.md](MANUAL_TEST.md) (the release checklist; step numbers below point to it) and
[DESKTOP_PLAN.md](DESKTOP_PLAN.md). It adds what that list does not say: which steps Claude Code can run from the
Mac and which need a person at the VM screen.

To run everything by hand without Claude Code, see [WINDOWS_VM_MANUAL_RUN.md](WINDOWS_VM_MANUAL_RUN.md).

## What CI already covers (do not repeat)

Unit tests, frozen-app smoke test with the fake backend, shell key flow, sidecar ends with the shell, silent install
into a Chinese-character folder, uninstall. This plan covers: a real window, a clean machine, SmartScreen and
antivirus, Explorer and dialogs, real providers (optional, 3 pages), and ARM64 Windows running the x64 build.

## Modes

- **Auto**: Claude Code runs it from the Mac over a control channel (see Setup) with PowerShell, plus screenshots
  (`utmctl` has no screenshot command; use `screencapture` on the UTM window, or a PowerShell screenshot in the guest).
- **Semi**: Claude Code prepares and checks it; one click or visual check by a person.
- **Manual**: only a person can judge or do it.

## Setup and control channel (Blocked until done)

UTM on Apple Silicon runs Windows with QEMU. Claude Code can drive the guest only through one of:

1. `utmctl exec` / `utmctl file push|pull`: needs the QEMU guest agent in Windows (UTM Guest Tools installer).
2. OpenSSH Server in Windows (Settings > Optional features), then `ssh user@<ip>` (`utmctl ip-address`).
3. A shared folder (UTM VirtualFS / SPICE WebDAV) for moving files only.

Nothing is installed in the VM without the owner's say-so. The VM must be snapshotted before the first run
(UTM: VM menu > Snapshot; or clone the VM). Revert to "clean baseline" after every run.

Facts to record each run: app version (installer name), `winver` build, `(Get-CimInstance Win32_Processor).Architecture`
(12 = ARM64), RAM and cores given to the VM.

## Tests

### P. Preparation

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| P1 | VM reachable | `utmctl list`, start VM, `utmctl ip-address` or `utmctl exec ... cmd /c ver` | VM running; one control channel works | Auto |
| P2 | Baseline snapshot | Snapshot named "clean baseline" | Exists before any install | Semi |
| P3 | WebView2 present | `Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'` | Version printed | Auto |
| P4 | Installer on guest | Push installer from its own empty folder on the Mac; check SHA-256 matches on both sides | Hashes equal | Auto |

### I. Install, uninstall, upgrade (MANUAL_TEST A1-A3, E29-E31)

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| I1 | x64 installer on ARM64 Windows | Run installer (silent: `/VERYSILENT /SUPPRESSMSGBOXES /LOG=...`) | Installs, no error. Record if ARM64 refuses `x64compatible` | Auto |
| I2 | SmartScreen / Defender | Run the installer by double-click from Explorer | Note the warning text; no block beyond "Run anyway" | Manual (A1, E31) |
| I3 | No admin prompt | Install as a standard user | No UAC prompt; files in `%LOCALAPPDATA%\Programs\BookTranslator` | Semi (A2) |
| I4 | Start menu / shortcut | Check `.lnk` in Start Menu Programs | "Book Translator" present | Auto (A4) |
| I5 | Uninstall | Run `unins000.exe /VERYSILENT` | Program folder gone; `%APPDATA%\BookTranslator` kept; Credential Manager entry kept | Auto (E29) |
| I6 | Upgrade over old version | Install old build, create a job and a key, install newer build over it | App starts; old job and key still present | Semi (E30) |
| I7 | Chinese Windows user name | Create a local user `测试用户`, install and start as that user | Works; data under that user's `%APPDATA%` | Semi |

### S. Startup and process cleanup (A3-A5)

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| S1 | Window opens in 15 s | Start `BookTranslator.exe`; poll `Get-Process` `MainWindowTitle` | Title present within 15 s; no console window | Auto |
| S2 | Close window | Close via `CloseMainWindow()` | No `BookTranslator` process left after 5 s | Auto |
| S3 | Kill main process | `Stop-Process` the main one | The `--sidecar` process exits too | Auto |
| S4 | Window looks right | Screenshot at 100% and 150% scale | Not cut off; Chinese text renders | Manual |
| S5 | Theme button | Click through themes, restart | Choice kept | Manual |

### K. Key storage (B7-B14) — no real keys

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| K1 | Credential Manager entry | After the app's key flow with a dummy key `sk-test-0000` (fake backend accepts), run `cmdkey /list` | `BookTranslator` entry exists | Semi (B13) |
| K2 | Key not on disk | `Get-ChildItem "$env:APPDATA\BookTranslator" -Recurse -File \| Select-String 'sk-test-0000'` | No match (including `sidecar.log`) | Auto |
| K3 | Delete key | Use Settings > delete | Entry gone; first-run note shows | Semi (B14) |
| K4 | Rejected key not kept | Fake backend rejects a marker key | "Provider rejected"; nothing stored | Semi (B10) |

### T. Translation with the fake backend (C16-C18, C21-C22, C26)

Start with `BOOKTRANS_FAKE_BACKEND=1` and `BOOKTRANS_DATA=<folder>` set in the environment of the launching process.

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| T1 | Frozen smoke test on the guest | Run the logic of `packaging\smoke_test.py` against the installed exe (copy the script over) | Passes under ARM64 emulation | Auto |
| T2 | PDF, EPUB, TXT | Upload each over HTTP to the sidecar (port from `--ready-file`), start, poll | `done`; PDF has original + Chinese page | Auto |
| T3 | Drag and drop and file button | Use the real window | Page count shown | Manual (C16) |
| T4 | Pause and continue | Cancel mid-run via API; continue | `Paused`, then finishes without redoing pages | Auto (C21) |
| T5 | Close during run | Kill shell mid-run, relaunch | Job shown paused; Continue works, no 409 | Auto (C22) |
| T6 | Delete this book's files | API delete | Files gone; UI returns to upload | Auto (C26) |

### C. Chinese paths and names (C20)

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| C1 | Chinese file name | Translate `化学之树.pdf` | Done; saved name right | Auto |
| C2 | Chinese folder path | Same file under `C:\测试\书籍` and in the user profile | Done | Auto |
| C3 | Native Save dialog / Show in folder | Click Save PDF, then Show in folder | Dialog suggests `<book>_bilingual.pdf`; Explorer opens on the file; Cancel is harmless | Manual (C24) |
| C4 | PDF viewers | Open the result in Edge and one other viewer | Chinese text shown and selectable | Manual (C25) |

### E. Error handling (B10-B11, C23)

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| E1 | No network | `Disable-NetAdapter`, then save a key / start a real-provider call | A "network" message, different from "rejected" | Auto (B11) |
| E2 | Network drop mid-run | Disable adapter during a run, re-enable | Job ends failed with a clear message; Continue finishes | Auto (C23) |
| E3 | Wrong key (real provider) | Dummy key against the real provider | "Rejected" message | Semi (B10) |

### R. Resources (D27-D28) — ARM64 numbers are not x64 numbers

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| R1 | Idle memory | `Get-Process BookTranslator` working set after 60 s idle | Recorded | Auto |
| R2 | Large scanned book | 400 pages, real provider, a few dollars | Peak under about 2 GB; no unbounded growth | Manual, optional |
| R3 | Low-RAM VM | Repeat T2 with the VM at 4 GB | Completes or fails clearly | Semi |

### W. Missing WebView2 (A6)

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| W1 | Runtime removed | Snapshot first. Uninstall the Evergreen runtime (Edge may block this; if so, rename the `EdgeWebView` folder), start the app | Understandable message, not a silent crash. Record what happens | Semi |

### O. Optional, real provider (3 pages only)

| ID | Check | Steps | Expected | Mode |
| --- | --- | --- | --- | --- |
| O1 | Preview 3 pages, text PDF | Real key typed by the owner, "Preview 3 pages" | Original page then Chinese page | Manual (C16) |
| O2 | Scanned PDF with OCR | Qwen or Anthropic, 3 pages; DeepSeek box disabled | Works / disabled as stated | Manual (C19) |
| O3 | Provider key pages | "How do I get a key?" for all four | Right page opens in the default browser | Manual (B9) |

## Reporting

One row per run in the Results log of [MANUAL_TEST.md](MANUAL_TEST.md); evidence under
`docs/vm-test-results/<date>/` (command output, screenshots, `sidecar.log` excerpts). Bugs are reported, not fixed,
in the run itself.
