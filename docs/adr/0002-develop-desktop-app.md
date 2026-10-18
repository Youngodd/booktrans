# ADR 0002: Develop a desktop app

- Status: Accepted. Supplements [ADR 0001](0001-choose-wechat-mini-program.md); the mini program is not removed.
- Date: 2026-10-18

## Context

After choosing a WeChat Mini Program (ADR 0001), we found a fit problem. The program needs an LLM API
(the backends include `api`, `qwen`, `deepseek` and `openai-compatible`). Most people apply for an API
key on the provider's website, and they do that on a computer. Getting that key into a phone mini
program is awkward: users must copy a long secret between devices and paste it into a small screen.

A desktop app runs where the key is already created. The user can paste it once, keep it on their own
machine, and run long jobs on a computer. Book translation is a long, heavy job, and PDFs usually live on
a computer.

We also think a desktop app may be easier to distribute. It is a file people download, so there is no
platform review and no domain or filing needed to hand it out. This is an expectation, not a verified
fact. TODO: confirm once we have tried to ship it.

TODO: the technology stack is not decided (for example, wrapping the existing Python package or using
an app framework).

## Decision

We develop a desktop app (macOS and Windows, TODO: confirm target platforms) that runs the translator locally with the user's own API key.

## Alternatives considered

- **Mini program only.** Keeps one client, but key entry is awkward on a phone and the platform review
  and WeChat rules still apply.
- **Web app.** Works on a computer with no install, but needs a domain and, for mainland users, probably
  an ICP filing, which is what ADR 0001 tried to avoid. A hosted server would also hold or proxy users' keys.
- **Command line tool only (status quo).** Works today, but is too hard for non-technical users.

## Consequences

Positive
- Fits the usual workflow: get a key on a website on the computer, paste it into the app.
- Keys and book files can stay on the user's machine, which lowers server cost and privacy burden.
- May be easier to distribute than a mini program, with no review by a platform.

Negative
- A second client to build and maintain next to the mini program and Web API.
- Users must download and install it, which is more friction than opening a mini program in WeChat.
- Updates are our job (an update mechanism, TODO: decide).

Risks
- **API key handling:** store the key in the OS keychain rather than plain text, never log it, and
  never send it anywhere except the chosen provider. TODO: decide the storage design.
- **Code signing and distribution:** unsigned apps trigger macOS Gatekeeper and Windows SmartScreen
  warnings. Signing and notarization cost money and time. TODO: estimate cost.
- Downloads inside mainland China may need a hosting place with good access. TODO: choose one.
- Users with no API key still need help getting one; the app should explain this.
