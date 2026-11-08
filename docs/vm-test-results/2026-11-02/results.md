# Run 2026-11-02: BookTranslator-Setup-0.1.19.exe on UTM Windows 11 (packer-vm-1735447014)

Installer: from BookTranslator-Setup.zip (one file, 86,834,258 bytes), extracted outside the repo.
SHA-256 (Mac): a0ec9772575f087a72c07fcb73b15939e7db38c692c01ab4fce1f5ac33f711a4

| ID | Status | Evidence |
| --- | --- | --- |
| P1 | Blocked: needs setup | VM starts (`utmctl start` ok). `utmctl ip-address` -> "QEMU guest agent is not running or not installed". No SSH either. |
| P2 | Pass (disk only) | `utmctl snapshot create <vm> --name "clean baseline"` works only with the VM stopped (GPU acceleration blocks snapshots of a running VM). `snapshot list`: "clean baseline  2026/11/2 19:40  disks only". |
| P3, P4, I*, S*, K*, T*, C*, E*, R*, W* | Blocked: needs setup | No control channel into the guest, so nothing can be pushed or run. |
| Screenshots | Blocked | `screencapture` -> "could not create image from display" (Screen Recording permission for the terminal, or no display session). |

Unblock: install UTM Guest Tools in Windows (UTM menu: CD/DVD > Install Windows Guest Tools, run the installer in the
guest, reboot), or enable OpenSSH Server. Then re-run. No bugs found yet; no app code was run.
