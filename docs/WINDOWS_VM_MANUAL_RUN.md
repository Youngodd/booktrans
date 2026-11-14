# Windows VM test: hand-run guide (no Claude Code)

Follow this at the UTM window. It replaces the Auto tests in [WINDOWS_VM_TEST_PLAN.md](WINDOWS_VM_TEST_PLAN.md) and
uses the step numbers of [MANUAL_TEST.md](MANUAL_TEST.md). Commands marked *verify* are standard Windows/UTM
behaviour that was not tried in this repo.

## 1. Get the installer into the VM and install it

**Move the file in (pick one):**

1. *Download inside Windows.* Put the zip somewhere Windows can fetch it (the CI artifact page, or on the Mac run
   `cd <folder-with-the-zip> && python3 -m http.server 8000 --bind 192.168.64.1`, then open
   `http://192.168.64.1:8000/BookTranslator-Setup.zip` in Edge). Stop the server afterwards (Ctrl+C).
2. *Shared folder.* Shut the VM down. UTM: VM settings > Sharing > Directory Share Mode "SPICE WebDAV" > pick a folder.
   Start the VM; the share appears under "My Computer" (or run `C:\Program Files\SPICE webdavd\map-drive.bat`). Needs UTM
   Guest Tools installed. *verify*
3. *Drag and drop onto the VM window.* Needs UTM Guest Tools. *verify*

**Check it arrived intact:**

```bash
shasum -a 256 BookTranslator-Setup-0.1.19.exe        # on the Mac
```
```powershell
Get-FileHash C:\temp\BookTranslator-Setup-0.1.19.exe -Algorithm SHA256   # in Windows
```
The two hashes must be identical. If the file is `BookTranslator-Setup.zip`, right-click > Extract All into a new,
empty folder (for example `C:\temp\bt`) and hash the `.exe` inside. The 0.1.19 installer's hash is
`a0ec9772575f087a72c07fcb73b15939e7db38c692c01ab4fce1f5ac33f711a4`.

**Install by double-click (MANUAL_TEST A1-A3):**

1. Double-click `BookTranslator-Setup-0.1.19.exe`.
2. If SmartScreen says "Windows protected your PC": click "More info", then "Run anyway". Write down the warning text.
3. There must be no administrator (UAC) prompt. Click through the wizard.
4. On the last page keep "Start Book Translator" ticked and click Finish.
5. A window must open within 15 seconds, with no black console window.

**Or install silently (for repeat runs):**

```powershell
Start-Process C:\temp\BookTranslator-Setup-0.1.19.exe -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/LOG=C:\temp\install.log' -Wait
```

**Check it worked:** the folder `%LOCALAPPDATA%\Programs\BookTranslator` exists, the Start menu has
"Book Translator", and `BookTranslator.exe` starts.

## 2. What you do by hand for each Auto test

Set this before launching the app from PowerShell when a test says "fake backend" (no API key, no cost):

```powershell
$env:BOOKTRANS_FAKE_BACKEND = "1"
$env:BOOKTRANS_DATA = "C:\测试\数据"
& "$env:LOCALAPPDATA\Programs\BookTranslator\BookTranslator.exe"
```
The variables only affect the process started from that window. Start the app from the Start menu for normal runs.

For the API tests, start the engine on its own and read its port and token:

```powershell
$ready = "C:\temp\ready.txt"; Remove-Item $ready -ErrorAction SilentlyContinue
$p = Start-Process "$env:LOCALAPPDATA\Programs\BookTranslator\BookTranslator.exe" -ArgumentList '--sidecar','--ready-file',$ready -PassThru
Start-Sleep 10; Get-Content $ready      # prints: port=NNNN token=XXXX
```

| ID | What to do | Pass looks like |
| --- | --- | --- |
| P1 | UTM: VM > Start; wait for the desktop | Desktop shown |
| P2 | Shut the VM down first (GPU acceleration blocks snapshots of a running VM). UTM > VM > Snapshots > create "clean baseline", or on the Mac `utmctl snapshot create <vm> --name "clean baseline"` | Snapshot listed |
| P3 | `Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'` | A version number is printed |
| P4 | Compare hashes as in section 1 | Identical |
| I1 | Run the installer (double-click or silent) on the ARM64 guest | Installs with no error. Record if Windows refuses the x64 installer |
| I4 | Look in Start menu, or `Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter *Book*` | "Book Translator" shortcut present |
| I5 | `& "$env:LOCALAPPDATA\Programs\BookTranslator\unins000.exe" /VERYSILENT` | Program folder gone; `%APPDATA%\BookTranslator` kept |
| S1 | Start the app and time it | Window within 15 s, no console window |
| S2 | Close the window, wait 5 s, `Get-Process BookTranslator -ErrorAction SilentlyContinue` | Nothing listed |
| S3 | Start the app. In Task Manager end the main `BookTranslator.exe`, then run `Get-Process BookTranslator` | The second (`--sidecar`) process is gone too |
| K2 | After saving a dummy key: `Get-ChildItem "$env:APPDATA\BookTranslator" -Recurse -File \| Select-String 'sk-test-0000'` | No output |
| T1 | `packaging\smoke_test.py` needs Python with PyMuPDF and httpx on the guest. Without them, do T2 instead | n/a |
| T2 | With the API running (see above): `curl.exe -H "X-Booktrans-Token: XXXX" -F "file=@C:\temp\sample.pdf" http://127.0.0.1:NNNN/api/jobs` then `.../api/jobs/<id>/start` (POST, JSON `{"auto_glossary": false}`) and poll `GET /api/jobs/<id>` | State becomes `done`; `GET /api/jobs/<id>/download` is a PDF with the original page then the Chinese page |
| T4 | Start a job, cancel it from the window, click Continue | "Paused", then finishes; finished pages not redone |
| T5 | Start a job, end the main process in Task Manager, start the app again | Job shown paused; Continue works, no error 409 |
| T6 | Use "Delete this book's files" | Book removed; upload block shown |
| C1 | Copy `化学之树.pdf` into the VM and translate it | Done; saved name is right |
| C2 | Repeat from `C:\测试\书籍` and from the user profile | Done |
| E1 | `Disable-NetAdapter -Name "*" -Confirm:$false` (admin), save a key in the app, then `Enable-NetAdapter -Name "*"` | A "network" message, not "rejected" |
| E2 | Disable the adapter during a translation, then enable it | Job fails with a clear message; Continue finishes it |
| R1 | After 60 s idle: `Get-Process BookTranslator \| Select Name,@{n='MB';e={[int]($_.WorkingSet64/1MB)}}` | Record the numbers (ARM64 emulation, not x64) |

No practical manual equivalent: S1's exact timing is a stopwatch estimate; E1/E2 need a working copy of the real
provider or a person watching the message. Say so in the log rather than guessing.

## 3. Setup, snapshots and recording

1. Record each run: installer name, `winver` build, `(Get-CimInstance Win32_Processor).Architecture` (12 = ARM64), the
   VM's RAM and cores (UTM > Edit VM).
2. Shut the VM down before creating or restoring a snapshot. Revert to "clean baseline" after every run.
3. Save evidence (copied command output, screenshots with Cmd+Shift+4 on the Mac) under `docs/vm-test-results/<date>/`.
4. Add one row to the Results log in `docs/MANUAL_TEST.md`.
5. Use no real API key except in the optional O tests, and then only "Preview 3 pages". Do not run R2 (it costs money).
6. Report bugs; do not fix app code in a test run.
