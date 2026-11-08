# End-to-end test scripts

Scripts for running the desktop app end to end with the **fake backend** (no provider calls, no cost). They are not
pytest tests (unit tests are in `tests/`); results of past runs are in `docs/vm-test-results/`. Follow
`docs/MANUAL_TEST.md` and `docs/WINDOWS_VM_TEST_PLAN.md` for what each step checks.

## mac/: the app from source on macOS

Needs the project venv (`.venv`). Nothing touches the real Keychain: `fakekr.py` is a file-backed keyring.
`shim.py` is the real desktop sidecar with only the backend swapped (slow it with `BOOKTRANS_SHIM_DELAY`, fail it while
the file named by `BOOKTRANS_SHIM_FAIL_FILE` exists, or reject the keys `sk-test-reject` / `sk-test-neterr`).
It also shortens the retry waits to 0.2 s.

| File | Does |
| --- | --- |
| `e2e.py REPO SCRATCH` | Translation, name review, cancel/continue, kill mid-run, delete, spend guard, provider failure, key not in files. SCRATCH is any empty working folder |
| `keyflow.py PHASE` | Key flow through the real shell `Api` (`first`, `restart`, `delete`); needs the env shown in its docstring and below |
| `window.py REPO SCRATCH` | Real window: opens in time, close leaves no process, `kill -9` of the shell (needs Accessibility permission for System Events) |
| `window2.py REPO SCRATCH` | Second start-up sample plus a region screenshot of only the app window |

```sh
S=$(mktemp -d)                      # empty scratch folder
.venv/bin/python tests/e2e/mac/e2e.py "$PWD" "$S"
# keyflow (run the three phases in order):
export BOOKTRANS_FAKE_BACKEND=1 BOOKTRANS_DATA=$S/kf FAKEKR_FILE=$S/kr.json PYTHON_KEYRING_BACKEND=fakekr.FileKR \
  PYTHONPATH=$PWD:$PWD/tests/e2e/mac REPO=$PWD BOOKTRANS_SIDECAR=$PWD/tests/e2e/mac/sidecar_shim.sh
for p in first restart delete; do .venv/bin/python tests/e2e/mac/keyflow.py $p; done
```

If `HTTP_PROXY` is set, add `NO_PROXY=127.0.0.1,localhost` (the shell's own client honours proxy variables: a known bug).
`packaging/ui_check.py` needs `PYTHONPATH=.`. Known result: `packaging/orphan_test.py` fails on macOS (Windows-only guard).

## windows-vm/: the installed app in a UTM Windows guest

Needs UTM with a Windows VM that has **UTM Guest Tools** (QEMU guest agent) and the installer
(`BookTranslator-Setup-<version>.exe`). The agent runs as SYSTEM and `utmctl exec` returns no output, so
`vmrun.sh` pushes a script, runs it, and reads back a file under `C:\Users\Public\bt`. Anything that needs the desktop
session (install, launching the app) uses `--user`, which goes through a temporary scheduled task (`btrun`) as the
guest user (`GUEST_USER`, default `vagrant`).

Before you start: stop the VM and snapshot it (`utmctl snapshot create <vm> --name ...`; a running VM cannot be
snapshotted). Restore the snapshot afterwards to undo everything.

```sh
export VM=<uuid-or-name>; D=tests/e2e/windows-vm
.venv/bin/python $D/make_vm_files.py /tmp/vmfiles            # small test books
utmctl exec $VM --cmd 'C:\Windows\System32\cmd.exe' /c 'mkdir C:\Users\Public\bt\files C:\Users\Public\bt\out'
for f in book12.pdf long300.pdf zh4.pdf book.epub book.txt; do utmctl file push $VM "C:\\Users\\Public\\bt\\files\\$f" < /tmp/vmfiles/$f; done
utmctl file push $VM 'C:\Users\Public\bt\BookTranslator-Setup-0.1.19.exe' < ~/Downloads/BookTranslator-Setup-0.1.19.exe
$D/vmrun.sh $D/p0.ps1                                         # who is logged in, WebView2 version
$D/vmrun.sh $D/p4.ps1                                         # installer size and SHA-256 (compare with shasum -a 256 on the Mac)
$D/vmrun.sh --user $D/i1.ps1 -t 300                           # silent install, Start menu
$D/vmrun.sh --user $D/s1.ps1 -t 150                           # window in 15 s, close, kill main (also saves s1.png in the guest)
$D/vmrun.sh --user $D/lib2.ps1 $D/t1.ps1 -t 360               # PDF/EPUB/TXT, range, preview, Chinese path, delete, spend guard
$D/vmrun.sh --user $D/lib2.ps1 $D/t2.ps1 -t 700               # cancel/continue, kill mid-run, memory
$D/vmrun.sh --user $D/lib2.ps1 $D/t3.ps1 -t 300               # cancel during the translate stage (no page redone)
$D/vmrun.sh --user $D/lib2.ps1 $D/r1.ps1 -t 150               # idle memory with the window open
$D/vmrun.sh --user $D/lib2.ps1 $D/i5.ps1 -t 150               # uninstall: program gone, data and credential kept
# cleanup: delete the scheduled task and C:\Users\Public\bt (see cleanup.bat; push it and run it as SYSTEM)
```

Outputs (the translated PDFs) are in `C:\Users\Public\bt\out`; pull them with `utmctl file pull` and read them with
PyMuPDF to check pages and Chinese text. `lib.ps1` + `k.ps1` (key flow through the real shell over the WebView2
debugging port) hung once and **overwrites the account's Credential Manager entry**: use only on a clean guest.
Windows PowerShell 5.1 decodes curl's UTF-8 as cp437, so Chinese file names look garbled in the logs; check the
download header instead.
