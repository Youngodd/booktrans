# ADR 0003: License the desktop app under AGPL-3.0

- Status: Accepted. Relates to [ADR 0002](0002-develop-desktop-app.md).
- Date: 2026-10-18

## Context

The desktop app (ADR 0002) will ship as a binary that bundles PyMuPDF (`import fitz`), which the engine
uses to read PDFs, find text blocks and redraw pages (`readers.py`, `layout.py`, `figures.py`).
PyMuPDF is dual-licensed by Artifex: AGPLv3, or a commercial license. The repository is currently MIT.

From <https://pymupdf.io/licensing> (read 2026-10-18):
- AGPLv3 is meant for open-source projects where users can receive the source code.
- Modified versions must stay AGPL, and users of a networked deployment must receive the source.
- The commercial license is for proprietary, SaaS and OEM use; no prices are published ("Contact Sales").
- The page does not discuss desktop distribution, MIT-licensed projects or binary bundling.

The last three points are our reading of the AGPL, not Artifex's statement, and this ADR is not legal advice.

The goals so far are a free, bring-your-own-key tool with no server of ours. We have no plan to sell a
closed-source product.

## Decision

Distribute the desktop app under **AGPL-3.0**, with the full source public in this repository.

- Replace `LICENSE` with AGPL-3.0 before the first public desktop release. Code already published under MIT
  stays available under MIT; the combined app is distributed under AGPL.
- The app has an About screen with the license name and a link to the source.
- Keep PyMuPDF's producer metadata in output PDFs.
- Include third-party license notices in the installer.
- Before the first release, check that every bundled dependency is AGPL-compatible (expected: reportlab,
  OpenCV, FastAPI, pypdf, openai, anthropic, fonttools and the shell are permissive). Record the result in
  `docs/THIRD_PARTY.md`.
- The hosted web service uses the same PyMuPDF, so its users are also entitled to the source. Keeping the
  repository public with a link on the page covers this.

## Alternatives considered

- **Buy a commercial license from Artifex.** Keeps the code closed and removes the source obligation. Cost
  is unknown and recurring, and we do not need closed source now. Revisit if we want a paid or closed product.
- **Replace PyMuPDF.** Avoids both options, but `layout.py` depends on it heavily (about 460 lines of block,
  table and page redrawing). Large rewrite with regression risk on scanned books. Not justified now.
- **Stay MIT and ship anyway.** Not an option for a binary that bundles PyMuPDF.

## Consequences

Positive
- No licence fee, no negotiation, no change to the engine.
- Clear story for users: the source is public and they can build it themselves.

Negative
- The app cannot later be closed-source or sold under proprietary terms without buying a commercial licence
  (or replacing PyMuPDF) and, for contributions we do not own, getting contributors' consent.
- Anyone may fork and redistribute under AGPL.
- Companies that avoid AGPL will not embed the code.

Risks
- Compatibility of every bundled dependency must be checked (see above).
- Our reading of how AGPL applies to a bundled desktop binary may be wrong; confirm with Artifex or a
  lawyer if the project grows or gains a commercial side.
- Contributions: decide whether to ask contributors for a licence grant (for example a DCO or CLA) so a
  future relicensing stays possible.
