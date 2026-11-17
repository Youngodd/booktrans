# Windows VM run, 2026-11-17: BookTranslator-Setup-0.1.33.exe on UTM Windows 11 ARM64

VM: `packer-vm-1735447014` (UUID 044F9555-1072-4B70-962A-C4F8C5C66505), Windows 11 build 26100 (10.0.26100) ARM64
(processor architecture 12), 4 GB RAM, 2 cores, guest user `vagrant`, WebView2 runtime 157.0.4341.42 (same as 11/14).
Run by Claude Code, fake backend only (no provider call, no cost).

## Versions

| Item | Before | After | Note |
| --- | --- | --- | --- |
| UTM (Mac app) | 5.0.8 | 5.0.8 | **Not updated.** Latest is 5.0.9 (2026-11-16). The download from GitHub ran at about 23 KB/s (305 MB, about 3.5 h); the user chose to skip it. |
| UTM Guest Tools in the VM | 0.1.271 | 0.1.271 | Already the latest: `utm-guest-tools-latest.iso` redirects to `utm-guest-tools-0.1.271.iso` (last modified 2025-07-18). No ISO was attached. QEMU guest agent 109.1.0, Spice webdavd 2.5.0, both services running. |

## Installer

`BookTranslator-Setup-0.1.33.exe` (from `~/Downloads/BookTranslator-Setup (3).zip`, unpacked in a scratch directory,
never run on the Mac), 82,411,220 bytes, SHA-256
`9799539a1d70d479faca1e779b52c26294bc5c118ad159be1f7aa4929f71b19a` on the Mac and in the guest (equal).
Harness note: `p4.ps1` and `i1.ps1` still hardcode `BookTranslator-Setup-0.1.19.exe`; scripts were not edited and the
0.1.33 file was pushed under that name. The hash identifies the build.

Snapshots: VM stopped and `pre-0.1.33-run` taken first; existing snapshots untouched. The VM was **not** restored
afterwards (it keeps the 0.1.33 uninstalled state, data folders removed by `cleanup.bat`).
Note: the installer is dated 2026-11-15 14:47, a few hours before the last commit; unit tests ran against the repo HEAD (955 passed, 2 skipped).

## Results

| ID | Result | Evidence | vs 11/14 (0.1.29) |
| --- | --- | --- | --- |
| P1 | pass | VM started, guest agent answered, `ip-address` listed, file push/pull worked | same |
| P2 | pass | Snapshot `pre-0.1.33-run` created with the VM stopped | same |
| P3 | pass | WebView2 157.0.4341.42 | same |
| P4 | pass | 82,411,220 bytes, SHA-256 equal on both sides | same |
| I1 | pass | `/VERYSILENT` exit 0 in 6 s, `BookTranslator.exe` 24,055,459 bytes, "Installation process succeeded", no restart | exe 430 KB larger; 8 s -> 6 s |
| I4 | pass | `Book Translator.lnk` in the user's Start Menu Programs | same |
| I5 | pass | Uninstaller exit 0: program folder gone, shortcut gone, data folder kept (5 jobs), Credential Manager entries kept (`api-key@BookTranslator`, `BookTranslator`) | same |
| S1 | pass | Window title "Book Translator" after 4.1 s; no console window; 1024x768 screenshot taken | 4.2 s -> 4.1 s |
| S2 | pass | After close: 0 BookTranslator processes | same |
| S3 | pass | Main process killed (780): no sidecar left | same |
| T2 | pass | PDF 12 -> 24 pages, Chinese on every even page; EPUB and TXT -> 2 pages, Chinese on page 2 (PyMuPDF, `python -I`) | same |
| T2 range/preview | pass | Range output 6 pages, first page "Page heading 3"; preview 6 pages | same |
| C1, C2 | pass | Chinese input path and data folder: `zh` job done, 4 -> 8 pages, Chinese on even pages; header `filename*=utf-8''%E5%8C%96%E5%AD%A6%E4%B9%8B%E6%A0%91_bilingual.pdf` | same |
| T4 (translate stage) | pass | `t3.ps1`: cancelled at stage `translate` (94/300), paused at 104 calls; Continue made 196 more (104 + 196 = 300), no page redone. The script's `redo=-104` line compares the resumed counter with the total and is not a redo | same result |
| T4 (`t2.ps1` part) | pass, weak | Cancel landed in stage `scan` (38/300, calls 0); Continue finished with 300 calls, peak 245 MB. Does not reach the translate stage; `t3` covers it | same |
| T5 | pass | Killed mid-run (33 done), relaunch: `paused`, Continue -> 200, finished `done` | same |
| T6 | pass | DELETE -> 200, job folder gone, GET -> 404 | same |
| Spend guard | pass | limit 3 -> `needs_decision` at 3.0, est. rest 9.0; finish-partial -> `done`, `partial` true | same |
| Security | pass | no token -> 401; PUT /api/key 200; key not in log; 0 files under the data dir contain the key | same |
| R1 | pass | Idle with window open: BookTranslator 182 MB (2 processes), msedgewebview2 591 MB (12 processes); idle sidecar 79 MB; 0 processes after close | not compared (no 11/14 number in the summary above) |

## Not run
- Manual-only rows (SmartScreen, window appearance, Save dialog, PDF viewers): need a person.
- `lib.ps1` + `k.ps1` (key flow): overwrites the account's Credential Manager entry.
- UTM 5.0.9 update (see Versions).

## Cleanup
`cleanup.bat` run as SYSTEM: `C:\Users\Public\bt` and the `C:\测试` data tree removed, scheduled task `btrun` gone
(`schtasks /query` -> not found). No guest-tools ISO was attached. New snapshot `pre-0.1.33-run` kept.
