# Third-party licenses

Dependency check required by [ADR 0003](adr/0003-license-desktop-app-under-agpl.md). Generated 2026-10-18 by
`packaging/third_party.py` from the installed package metadata (macOS development environment, 55 packages).
The compatibility column is a rough guide from the license name, not legal advice.

## Result

- No package in the list has a license that conflicts with distributing the combined app under AGPL-3.0. The
  licenses are MIT, BSD, Apache-2.0, MPL-2.0 (certifi, tqdm), PSF, MIT-CMU (pillow), and two AGPL-3.0 packages:
  **PyMuPDF** (dual-licensed AGPL or Artifex commercial; we use it under the AGPL) and **EbookLib** (AGPL-3.0 or
  later), which is consistent with the project's AGPL license.
- Apache-2.0 packages (openai, opencv-python-headless, python-multipart, importlib_metadata) are compatible with
  AGPL-3.0 (version 3 of the GPL family), but not with GPL-2.0-only; nothing here is GPL-2.0-only.
- The `pyobjc-*` rows are macOS-only and are not in the Windows build. The Windows build also contains pythonnet,
  clr-loader, cffi, pycparser and pywin32-ctypes, which are not in this list because it was generated on macOS;
  they are expected to be MIT or BSD but have not been checked.

## Not verified

- Binary components shipped inside wheels or the bundle that the package metadata does not describe: the Python
  runtime (PSF license), the WebView2 loader DLLs that pywebview ships (Microsoft), and any libraries inside the
  OpenCV and PyMuPDF wheels. Check these against each wheel's own license files before a public release.
- The license field is whatever each package declares; it was not compared with its source repository.
- PyMuPDF's AGPL obligations: source for the app is public in this repository; output PDFs keep PyMuPDF's producer
  metadata (not changed by our code). Whether bundling is fully covered by this reading of the AGPL is the open
  question recorded in ADR 0003.

## Packages

| Package | Version | License (from metadata) | AGPL-3.0 compatible? |
| --- | --- | --- | --- |
| annotated-doc | 0.0.5 | MIT | yes |
| annotated-types | 0.7.0 | MIT License | yes |
| anthropic | 0.125.0 | MIT License | yes |
| anyio | 4.12.1 | MIT | yes |
| backports.tarfile | 1.2.0 | MIT License | yes |
| beautifulsoup4 | 4.15.0 | MIT License | yes |
| bottle | 0.13.4 | MIT License | yes |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | yes |
| charset-normalizer | 3.5.2 | MIT | yes |
| click | 8.1.8 | BSD License | yes |
| distro | 1.9.0 | Apache Software License | yes |
| docstring_parser | 0.18.0 | MIT License | yes |
| EbookLib | 0.20 | GNU Affero General Public License v3 or later (AGPLv3+) | yes |
| exceptiongroup | 1.3.1 | MIT License | yes |
| fastapi | 0.128.8 | MIT | yes |
| fonttools | 4.60.2 | MIT | yes |
| h11 | 0.16.0 | MIT License | yes |
| httpcore | 1.0.9 | BSD-3-Clause | yes |
| httpx | 0.28.1 | BSD License | yes |
| idna | 3.20 | BSD-3-Clause | yes |
| importlib_metadata | 8.7.1 | Apache-2.0 | yes |
| jaraco.classes | 3.4.0 | MIT License | yes |
| jaraco.context | 6.1.1 | MIT | yes |
| jaraco.functools | 4.4.0 | MIT | yes |
| jiter | 0.16.0 | MIT | yes |
| keyring | 25.7.0 | MIT | yes |
| lxml | 6.1.3 | BSD-3-Clause | yes |
| more-itertools | 10.8.0 | MIT | yes |
| numpy | 2.0.2 | BSD License | yes |
| openai | 2.48.0 | Apache Software License | yes |
| opencv-python-headless | 5.0.0.93 | Apache Software License | yes |
| pillow | 11.3.0 | MIT-CMU | yes |
| proxy_tools | 0.1.0 | MIT License | yes |
| pydantic | 2.13.5 | MIT | yes |
| pydantic_core | 2.46.5 | MIT | yes |
| PyMuPDF | 1.26.5 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License | yes |
| pyobjc-core | 11.1 | MIT | yes |
| pyobjc-framework-Cocoa | 11.1 | MIT | yes |
| pyobjc-framework-Quartz | 11.1 | MIT | yes |
| pyobjc-framework-Security | 11.1 | MIT | yes |
| pyobjc-framework-UniformTypeIdentifiers | 11.1 | MIT | yes |
| pyobjc-framework-WebKit | 11.1 | MIT | yes |
| pypdf | 6.19.0 | BSD-3-Clause | yes |
| python-multipart | 0.0.20 | Apache-2.0 | yes |
| pywebview | 6.2.1 | BSD License | yes |
| reportlab | 5.0.1 | BSD License | yes |
| six | 1.17.0 | MIT License | yes |
| sniffio | 1.3.1 | MIT License; Apache Software License | yes |
| soupsieve | 2.8.4 | MIT | yes |
| starlette | 0.49.3 | BSD-3-Clause | yes |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | yes |
| typing_extensions | 4.16.0 | PSF-2.0 | yes |
| typing-inspection | 0.4.2 | MIT | yes |
| uvicorn | 0.39.0 | BSD-3-Clause | yes |
| zipp | 3.23.1 | MIT | yes |
