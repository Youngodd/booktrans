# Manual test checklist: desktop app

What CI cannot check: a person using the window, real providers, a clean machine. Run this before each
release. CI already covers (do not repeat by hand): unit tests, the frozen app translating 2 pages with a fake
backend, the key and proxy flow in the shell, the sidecar ending with the shell, silent install into a folder with
Chinese characters, uninstall.

Mark each line pass / fail and note the app version (the installer name, e.g. `BookTranslator-Setup-0.1.7.exe`)
and Windows version. Use a clean Windows 10 or 11 machine or a snapshot of a VM; take a snapshot before installing.

Costs: real-provider steps use "Preview 3 pages" or a short page range, a few cents at most.

## A. Install and start

1. Download the installer from the CI artifact (or Releases). Run it. Windows may warn (SmartScreen) until M4
   signing is done: click "More info", "Run anyway". Note the warning text.
2. The installer needs no administrator prompt. Finish it with "Start Book Translator" ticked.
3. A window opens within about 15 seconds; no black console window appears at any time.
4. Start menu has "Book Translator". Close the window; check Task Manager: no `BookTranslator.exe` left running.
5. Open again, then end `BookTranslator.exe` (the main one) in Task Manager: the second `BookTranslator.exe` (the
   sidecar) disappears too.
6. Machine without WebView2 runtime (Windows 10 older than 2018, or removed): the app should say something
   understandable, not crash silently. Record what happens.

## B. First run, key, proxy

7. First run shows the upload block first and the key panel below it, with the privacy note.
8. Language default: on a Chinese-language Windows the provider starts on Qwen (China); on an English one, Anthropic.
9. "How do I get a key?" opens the right provider page in the default browser, for each of the four providers.
10. Wrong key: "Save and test" says the provider rejected it; the key is not kept (close and reopen: first-run again).
11. No network (disconnect): a different message from "rejected" (network or proxy).
12. Correct key: saved. Close and reopen the app: no key prompt, the provider shown is the saved one.
13. Windows Credential Manager (Control Panel > Credential Manager > Windows Credentials) has an entry named
    `BookTranslator`; no file under `%APPDATA%\BookTranslator` contains the key (search the folder for part of it).
14. Settings: delete the stored key: the entry disappears from Credential Manager and first-run shows again.
15. Proxy: with a working proxy address (and the system proxy off), save it and test a key: works. Enter a wrong
    address: the key test says it cannot reach the provider. Clear it: the system proxy settings apply again.
    If the address has a password, it must not be shown anywhere in the window afterwards.

## C. Translating

16. PDF with text, about 20 pages: choose it (button and drag and drop), page count shown, set a range, Preview 3
    pages: finishes; the result has the original page then the Chinese page, layout kept.
17. Same book, "Review the names": the name list appears, edit one rendering, continue: the edited rendering is used.
18. EPUB and TXT files each translate.
19. Scanned PDF (no text layer) with OCR ticked: works with Anthropic and Qwen; for DeepSeek the OCR box is disabled.
20. File name with Chinese characters and a path with Chinese characters: opens, translates, the saved file name is
    right.
21. Cancel while running: becomes "Paused"; Continue finishes the book without re-translating finished pages
    (watch the provider's usage page or the progress count).
22. Close the app while a book is running, reopen: the book is shown as paused, Continue works (no error 409).
23. Pull the network cable mid-run: the job ends as failed with a clear message; Continue finishes it afterwards.
24. Done: "Save PDF" opens the Windows save dialog with the suggested name `<book>_bilingual.pdf`; saving works;
    "Show in folder" opens Explorer on that file. Cancelling the dialog does nothing bad.
25. Open the saved PDF in two different viewers: Chinese text shows (no empty boxes) and can be selected.
26. "Delete this book's files" removes the book; the app returns to the upload block.

## D. Long and heavy

27. A 400-page scanned book with OCR (one run, real provider, a few dollars): watch memory in Task Manager; it
    should not grow without bound or exceed about 2 GB. Note the peak and the time per page.
28. Run it on a machine with 8 GB RAM or less if available.

## E. Uninstall and upgrade

29. Uninstall from Settings > Apps: the program folder is gone; `%APPDATA%\BookTranslator` (jobs, logs) is kept.
    The Credential Manager entry is kept; delete it by hand or from Settings in the app before uninstalling.
30. Install a newer installer over the old one: the app starts, the old books and the key are still there.
31. Antivirus: note any warning from Windows Defender or another scanner on the installer or the app.

## F. Mac development run (for the maintainer)

32. `cd ~/Developer/book-translator && .venv/bin/python -m booktrans.desktop.shell` opens the window. macOS may ask
    to use the Keychain: allow it. Steps B and C above apply except the Windows-only ones.
33. `.venv/bin/python packaging/ui_check.py` opens a window for a few seconds and prints `UI CHECK OK`.

## Results log

| Date | Version | Windows | Tester | Failed steps | Notes |
| --- | --- | --- | --- | --- | --- |
