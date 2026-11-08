# Windows VM run, 2026-11-08: BookTranslator-Setup-0.1.19.exe on UTM Windows 11 ARM64

VM: `packer-vm-1735447014` (UTM 5.0.8, QEMU), Windows 11 Pro build 26100, ARM64 (Architecture 12), 2 CPUs, 4 GB RAM,
1024x768, guest user `vagrant`, UTM Guest Tools installed (QEMU-GA, SPICE VDAgent, spice-webdavd running).
Installer: SHA-256 a0ec9772...f711a4 on the Mac and in the guest (equal). Run by Claude Code, fake backend
(`BOOKTRANS_FAKE_BACKEND=1`), no real provider, no real key.

Control channel: `utmctl exec` / `file push` / `file pull` through the guest agent. The agent runs as SYSTEM, so
anything that must run as the desktop user went through a temporary scheduled task (`/RU vagrant /IT`), deleted at
the end. `exec` returns no output, so each script wrote a file under `C:\Users\Public\bt` that was pulled back.
A snapshot `guest-tools baseline` was taken first (VM stopped, snapshotted, restarted); restore it to undo everything.

## Results

| ID | Result | Evidence |
| --- | --- | --- |
| P1 | pass | `utmctl list`, agent answers, `ip-address` and file push/pull work |
| P2 | pass | Snapshot `guest-tools baseline` (the older `clean baseline` predates Guest Tools) |
| P3 | pass | WebView2 runtime 157.0.4341.42 |
| P4 | pass | 86,834,258 bytes, hash equal both sides |
| I1 | pass | x64 installer on ARM64 Windows: `/VERYSILENT` exit 0 in 8 s, installed to `%LOCALAPPDATA%\Programs\BookTranslator` |
| I3 | pass (partly) | Per-user path, no UAC in silent mode. Not clicked through as a standard user |
| I4 | pass | `Book Translator.lnk` in the user's Start Menu Programs |
| I5 | pass | Uninstaller exit 0: program folder gone, shortcut gone, `%APPDATA%\BookTranslator` kept (1 job), Credential Manager entry kept |
| S1 | pass | Window title "Book Translator" 3.8 s after start; no console window found. `app-window-vm.png` |
| S2 | pass | `CloseMainWindow()`: 0 `BookTranslator` processes after 6 s |
| S3 | pass | Killed the main process (`Stop-Process -Force`): the `--sidecar` process was gone 5 s later (job object works) |
| T2 | pass | PDF 12 -> 24 pages (page 1 original, page 2 Chinese); EPUB and TXT -> 2 pages each, Chinese present (outputs pulled to the Mac and read with PyMuPDF) |
| T2 range/preview | pass | `3-5` -> 6 pages starting at page 3; preview -> 6 pages |
| C1, C2 | pass | `C:\测试\书籍\化学之树.pdf` as input and `C:\测试\书籍\数据` as the data folder: done; download header `filename*=utf-8''化学之树_bilingual.pdf` |
| T4 | pass | 300-page book cancelled during `translate` at 86 calls (paused); Continue made 214 more calls: 86 + 214 = 300, no page redone |
| T5 | pass | App/sidecar killed mid-run, relaunched on the same data: job `paused`, Continue -> 200 (no 409), finished `done` |
| T6 | pass | DELETE -> 200, job folder gone, GET -> 404 |
| Spend guard | pass | limit ¥3 -> `needs_decision` at ¥3.00, est. rest ¥9.00; finish-partial -> `done`, `partial` true |
| K2 | pass | `sk-test-0000` in no file under the data folder, including `sidecar.log`; no-token request -> 401 |
| R1 | recorded | App idle 60 s: BookTranslator x2 = 257 MB, WebView2 x12 = 620 MB. During a 300-page run the sidecar peaked at 250 MB (ARM64 emulating x64, fake backend) |
| K1, K3 | **not run** | A `BookTranslator` Credential Manager entry (user `api-key`) already existed for `vagrant`, with a job from 11/3 in `%APPDATA%\BookTranslator`. Saving a test key would overwrite it, so it was left alone and all tests used separate data folders |
| K4, E1, E2 | not run | The frozen app's fake backend accepts every key and makes no network calls, so a rejected key or a network cut cannot be provoked from outside (Mac run covered these against a test shim) |
| I2, S4, S5, T3, C3, C4 | needs a person | SmartScreen, 100%/150% scaling, theme button, drag and drop, Save dialog, Show in folder, PDF viewers |
| I6, I7, W1, R2, R3 | not run | No old build to upgrade from; no second user created; WebView2 not removed; no real 400-page book; VM RAM not changed |
| O1-O3 | not run | Real provider; owner only |

## Bugs found

None in the app on Windows. The two Mac findings (proxy variables break the shell's calls to its sidecar; token in
`sidecar.log`) were not retested here; the VM has no proxy variables set.

## Things done to the guest, and left behind

- Snapshot `guest-tools baseline` added (VM was stopped for it, then restarted).
- Two lines (`BOOKTRANS_READY ...`) were appended to the owner's existing `%APPDATA%\BookTranslator\sidecar.log` by an
  aborted early script (it launched the app on the default data folder). Nothing else there or in Credential Manager
  changed; the pre-existing job and credential were verified unchanged afterwards.
- Early in the health check a stray `C:\Windows\Temp\x.txt` was written by mistake; it was deleted.
- Removed at the end: `C:\Users\Public\bt`, `C:\测试`, the `btrun` scheduled task, the installed app.

Harness notes: my first translation script lost its log lines because a variable named `$out` shadowed the global
`$OUT` (PowerShell is case-insensitive); results were recovered from the output PDFs. The `σîû...` file name in that
log is PowerShell 5.1 decoding curl's UTF-8 as cp437, not an app bug.

Scripts: `tests/e2e/windows-vm/` (see `tests/e2e/README.md`).
