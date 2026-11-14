# Windows VM run, 2026-11-14: BookTranslator-Setup-0.1.29.exe on UTM Windows 11 ARM64

VM: `packer-vm-1735447014` (UUID 044F9555-1072-4B70-962A-C4F8C5C66505), Windows 11 build 26100 ARM64, guest user
`vagrant`, UTM Guest Tools (QEMU guest agent) answering, WebView2 runtime 157.0.4341.42. Run by Claude Code, fake
backend only (no provider call, no cost).

Installer: `BookTranslator-Setup-0.1.29.exe` (from `~/Downloads/BookTranslator-Setup (2).zip`, unpacked in a scratch
directory, never run on the Mac), 81,941,875 bytes, SHA-256
`23417cbb843f6c16f6501a59beaa81de1eb600422d7156c9543b1ce63cf39b9d` on the Mac and in the guest (equal).

Harness note: `p4.ps1` and `i1.ps1` hardcode the file name `BookTranslator-Setup-0.1.19.exe`. Scripts were not edited;
the 0.1.29 file was pushed to the guest under that name. The hash above, not the file name, identifies the build.
The installer's own log and Start menu entry were created by this file (install log dated 2026-11-13).

Snapshots: the VM was stopped and a snapshot `pre-0.1.29-run` was taken first (so the restore returns the VM to the
state it was in, including anything done since 11/8). Existing snapshots `guest-tools baseline` and
`clean baseline` were not touched. After the run the VM was restored to `pre-0.1.29-run`.

## Results

| ID | Result | Evidence |
| --- | --- | --- |
| P1 | pass | VM started from stopped, guest agent answered, `ip-address` listed, file push/pull worked |
| P2 | pass | Snapshot `pre-0.1.29-run` created with the VM stopped |
| P3 | pass | WebView2 runtime 157.0.4341.42 (same as 11/8) |
| P4 | pass | 81,941,875 bytes, SHA-256 equal on both sides |
| I1 | pass | `/VERYSILENT` exit 0 in 8 s, installed to `%LOCALAPPDATA%\Programs\BookTranslator` (`BookTranslator.exe` 23,625,766 bytes, `_internal`, `unins000.exe`), "Installation process succeeded", no restart |
| I4 | pass | `Book Translator.lnk` in the user's Start Menu Programs |
| I5 | pass | Uninstaller exit 0: program folder gone, shortcut gone, data folder kept (3 jobs), Credential Manager entries kept (`api-key@BookTranslator`, `BookTranslator`) |
| S1 | pass | Window title "Book Translator" after 4.2 s (11/8: 3.8 s); no console window; screenshot `app-window-vm.png` shows the UI |
| S2 | pass | After `CloseMainWindow()`: 0 BookTranslator processes |
| S3 | pass | Main process killed: no sidecar left |
| T2 | pass | PDF 12 -> 24 pages, Chinese on every even page; EPUB and TXT -> 2 pages, Chinese on page 2 (pulled and read with PyMuPDF) |
| T2 range/preview | pass | Range output 6 pages, first page text "Page heading 3"; preview 6 pages |
| C1, C2 | pass | `C:\测试\书籍\...` Chinese input path and Chinese data folder: `zh` job done, 4 -> 8 pages; download header `filename*=utf-8''%E5%8C%96%E5%AD%A6%E4%B9%8B%E6%A0%91_bilingual.pdf` |
| T4 (translate stage) | pass | `t3.ps1`: cancelled at stage `translate` (53/300), paused at 86 calls; Continue made 214 more calls (86 + 214 = 300), no page redone |
| T4 (`t2.ps1` part) | pass, weak | Cancel landed in stage `scan` (69/300, calls 0), paused, Continue finished with 300 calls, peak 239 MB. This run did not hit the translate stage; `t3` covers that |
| T5 | pass | Killed mid-run (45 done), relaunch: `paused`, Continue -> 200, finished `done` |
| T6 | pass | DELETE -> 200, job folder gone, GET -> 404 |
| Spend guard | pass | limit 3 -> `needs_decision` at 3.0, est. rest 9.0; finish-partial -> `done`, `partial` true |
| K2 | pass | `sk-test-0000` not in `sidecar.log` or any file under the data folder (0 files); no-token request -> 401 |
| R1 | recorded | Idle with window open: BookTranslator x2 = 256 MB (11/8: 257), WebView2 x12 = 641 MB (11/8: 620). Idle sidecar 79 MB; peak 239 MB in a 300-page run (11/8: 250) |
| K1, K3 | not run | `k.ps1`/`lib.ps1` not requested; they overwrite the Credential Manager entry |
| K4, E1, E2 | not run | Fake backend accepts every key and makes no network calls |
| I2, I3, S4, S5, T3, C3, C4 | not run | Need the desktop GUI or a person (SmartScreen, scaling, theme button, drag and drop, Save dialog, PDF viewers; B13/B14, C24, C25) |
| I6, I7, W1, R2, R3 | not run | No old build to upgrade from, no second user, WebView2 not removed, no real 400-page book, RAM not changed |
| O1-O3 | not run | Real provider; owner only |

## Regressions against 0.1.19

None found. Timings and memory are within a few percent of the 11/8 run. Hangs: none; no step needed a retry.

## Notes

- `t1.ps1` calls `PUT /api/key` (200) against the frozen app. Whatever that did to the guest's Credential Manager entry
  was discarded by the snapshot restore.
- The data folder had 3 jobs before uninstall (11/8: 1); this is VM state, not an app change.
- `t2.ps1` printed `calls=` empty at pause because the cancel hit the scan stage, as noted in the table.
- The `σîû...` name in `t1` output is PowerShell 5.1 decoding UTF-8 as cp437; the download header above is correct.

## Left on the guest

Nothing: `cleanup.bat` removed `C:\Users\Public\bt`, `C:\测试` and the `btrun` task (verified), then the VM was restored
to `pre-0.1.29-run`. The snapshot `pre-0.1.29-run` remains and can be deleted if not wanted.

Scripts: `tests/e2e/windows-vm/` (see `tests/e2e/README.md`). Not modified.
