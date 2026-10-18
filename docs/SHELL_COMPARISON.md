# Desktop shell comparison: Tauri vs pywebview

Status: pywebview prototype built; Tauri assessed from documentation only (no Rust toolchain here, no Tauri build).
Feeds the "Shell choice" decision in [DESKTOP_PLAN.md](DESKTOP_PLAN.md).

## What was built

`booktrans/desktop/shell.py` (pywebview) does everything the plan asks of a shell except the final UI:
- starts the sidecar and reads its `BOOKTRANS_READY port= token=` line;
- keeps the API key in the OS credential store (`keyring`; Windows Credential Manager), checks it with the
  provider through the sidecar before storing, and hands it to the sidecar once per session;
- exposes `connection`, `has_key`, `save_key`, `delete_key`, `use_stored_key`, `save_pdf` (native save dialog)
  to the page; the key never goes back to the page;
- puts the sidecar in a Windows job object (kill-on-close), so it dies even if the shell is killed.

Verified on macOS: `--headless-check` (key stored, handed over, deleted). Windows CI runs the same check, an
orphan test (kill the shell hard, expect the sidecar gone) and a PyInstaller build of the shell for size.
Not verified: the window itself, native dialogs, and the page sending the token header (M2 work).

## Comparison

| | pywebview + PyInstaller | Tauri + sidecar |
| --- | --- | --- |
| Toolchain | Python only (already have it) | Adds Rust and Node tooling |
| Credential store | Python `keyring`, built and tested | Rust `keyring` crate, not tried |
| Sidecar lifecycle | Job object in ~30 lines of ctypes, tested in CI | Tauri spawns sidecars but orphan handling is ours to verify |
| Webview | WebView2 on Windows (needs the runtime; Windows 10 2018+ and 11 ship it) | WebView2; installer can download it (no size), embed a bootstrapper (+1.8 MB) or the offline installer (+127 MB) |
| Installer and updater | Hand-built (Inno Setup/NSIS, own update check) | Built in (NSIS/MSI, updater plugin) |
| Packaging risk | pywebview needs `clr`/pythonnet bundled correctly under PyInstaller | A reported NSIS bug: an `externalBin` sidecar is not replaced on reinstall, silently leaving a stale one ([issue 15134](https://github.com/tauri-apps/tauri/issues/15134)); one report, unconfirmed |
| Size | Shell adds a few MB on top of the sidecar (CI number pending) | Small shell, but the Python sidecar dominates either way |
| Native feel | Basic | Better |

Sources: [Tauri Windows installer docs](https://v2.tauri.app/distribute/windows-installer/), the issue above,
pywebview packaging notes (pythonnet/`clr` hidden import).

## Recommendation

Use **pywebview for the MVP**. The plan's deciding factors were the updater, the maintenance load of Rust for a
solo maintainer, and the spike. Rust is a real extra burden, the shell logic already works in Python and is
testable in CI, and the Python bundle dominates size either way. The cost is a hand-built installer and update
check (both deferred in the plan anyway; M3 builds the installer).

Revisit Tauri if: the Windows build shows pywebview is fragile under PyInstaller, a built-in updater becomes a
priority, or a native look matters. The sidecar's HTTP+token interface means the shell can be swapped without
touching the engine.

## Windows CI result

Run on commit `2b0cdcf`: tests, the key flow with the real Windows credential store, the orphan test
(killing the shell hard also ended the sidecar) and the PyInstaller build of the shell all passed.
Still open: the shell bundle size (in the run's job summary) and anything that needs a visible window.
