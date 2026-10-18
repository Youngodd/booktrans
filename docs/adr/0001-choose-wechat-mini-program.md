# ADR 0001: Choose a WeChat Mini Program as the first client

- Status: Accepted (original decision). Supplemented by [ADR 0002](0002-develop-desktop-app.md), which adds a desktop app.
- Date: 2026-10-18 (records a decision made earlier; TODO: add the original decision date)

## Context

book-translator turns English books (PDF / EPUB / TXT) into bilingual PDFs. We wanted to offer it to
users in mainland China as an online service, so we needed a client that people can reach without
installing the Python tool.

The obvious choice is a website. A website needs its own domain, and a domain that serves users in
mainland China generally needs an ICP filing (备案). The filing takes time and has conditions
(see `docs/LEGAL_DISCUSSION.md`). Individual filings are limited to personal-style content, and the
rules differ between cloud vendors. TODO: confirm the exact current filing rules with the vendor or authority.

A WeChat Mini Program looked easier to get online. We thought it would be easier to pass the filing
for a mini program than for a website with its own domain. The Cloud Hosting route (微信云托管,
see `docs/NEXT_STEPS.md`) also lets the mini program reach the server without us owning a domain.
Mini programs bring their own sign-in and distribution through WeChat, and the platform has a review
process we have to pass.

This was an expectation, not a verified fact.

## Decision

We build the first client as a WeChat Mini Program (`miniprogram/`) backed by the Web API in this repo.

## Alternatives considered

- **Website with its own domain.** The most flexible, with no platform review. Rejected for now
  because of the expected ICP filing effort for the domain.
- **Website on an overseas server, no filing.** Avoids ICP, but mainland access may be slow or
  blocked, and a public-security filing may still apply (sources disagree).
- **Open source / self-host only.** No hosting or filing, but it excludes non-technical users.

## Consequences

Positive
- Skips the domain and ICP filing that a website would need, if the assumption holds.
- Users reach the app inside WeChat, with no install beyond WeChat itself.

Negative
- We still go through the mini program review. Some service categories need a business license,
  and the package size is limited (2 MB main package, 20 MB total).
- The work is tied to WeChat's tooling and rules, and shares little code with a website or desktop app.
- The tool needs an LLM API key, and these are usually applied for on a provider's website, which is
  awkward on a phone (see ADR 0002).

Risks and assumptions to verify
- **Assumption:** the mini program passes review more easily than a website passes ICP filing.
  TODO: verify; record the real outcome and effort here.
- Platform rules may change, and a payment feature would need an enterprise account.
- Running the backend still costs money and needs a privacy policy and declaration.
