# Legal and market discussion (2026-10-14)

Notes from a planning session. Not legal advice: the legal part was a role-play
as a Chinese tech lawyer for issue spotting. Have a licensed lawyer review it
before charging users or promoting to mainland China. Search findings come from
vendor docs and tech blogs, not official statutes; verify before relying on them.

## 1. Is there a better translator?

| Project | Strength | Gap vs. this project |
| --- | --- | --- |
| BabelDOC (funstory-ai) | Layout-preserving PDF translation, formula placeholders, terminology consistency; engine behind Immersive Translate's PDF service | Built for papers/technical docs; nothing found on scanned books, OCR cleanup or table rebuilding |
| PDFMathTranslate / pdf2zh-next | Scientific papers, keeps formulas and charts, bilingual output, web UI | Same: papers, not scanned books |
| Immersive Translate (hosted) | Polished product with free quota | A competing service, not code |

- This project's niche: whole books, scanned pages with a rough text layer,
  OpenCV scan cleanup, cell-by-cell tables, English page followed by Chinese page.
- Competitors have more users, more testing, better formula handling.
- Not verified: output quality was not compared; EPUB-focused tools (e.g.
  bilingual_book_maker) were not checked.

Sources: [BabelDOC paper](https://preview.aclanthology.org/ingest-acl/2026.acl-demo.25/),
[Medium overview](https://medium.com/@turgutgvcn/how-llms-can-actually-translate-pdfs-layout-matters-f990b175b6e7),
[PDFMathTranslate mirror](https://github.com/BeringLab/PDFMathTranslate).

## 2. Is an ICP filing worth it?

- Alibaba Cloud: a domain pointing at a mainland server needs ICP filing; pointing at an
  overseas server (e.g. Hong Kong) does not, but may need the public-security filing
  (two Alibaba pages disagree on that). Tencent Cloud words it more strictly: any site
  serving users in China must file.
- Individual filings are limited to personal-style content. A paid service generally
  needs a company, and possibly a commercial telecom (ICP) license.
- AI rules: calling a third-party model that is already filed, without fine-tuning,
  usually means registering the service with the local cyberspace administration (CAC);
  some sources also mention an algorithm filing. Sources disagree; ask the local CAC.
- Recommendation: do not file yet. Launch on the overseas server (Singapore/Tokyo, as in
  `docs/DEPLOY.md`), measure mainland access and speed, file only if real demand is blocked.
  Alternative: open-source / self-host, where users bring their own key and no hosting or
  filing is needed.

Sources: [Alibaba ICP process](https://help.aliyun.com/zh/icp-filing/new-website-process),
[Tencent Cloud](https://cloud.tencent.com/document/product/243/18907),
[Huawei Cloud](https://support.huaweicloud.com/topic/723290-1-G),
[CSDN article](https://adg.csdn.net/695246ba5b9f5f31781b53ea.html).

## 3. Legal risk review (as a Chinese tech lawyer)

### Facts taken from the code

- Users upload PDF/EPUB/TXT; the server stores it, builds a bilingual PDF, deletes after 24h.
- Users bring their own API key, held in memory only.
- No login; the random job_id is the access token.
- No terms, no copyright notice, no takedown contact (`DEPLOY.md` says to add them).
- Planned server: overseas. Suppliers: Claude, Qwen, DeepSeek, custom.
- The Privacy text says nothing about files being sent to the chosen model vendor.

### Risks, highest first

1. **Copyright (highest).** Storing the book is reproduction; the translation falls under
   the translation right (Copyright Law art. 10). The "safe harbour" for service
   providers (Information Network Dissemination Regulation; Civil Code arts. 1195-1197)
   needs a notice-and-takedown process, no actual or constructive knowledge, and no direct
   profit. Weak points: no takedown channel yet; whole-book translation is mostly used on
   copyrighted books, so "should have known" is arguable; charging fees weakens the
   defence. An overseas server does not shield you if you or your assets are reachable.
   Foreign rights holders can sue too.
2. **Content safety.** Uploaded or generated text may contain illegal content. The
   Cybersecurity Law and content-governance rules expect handling measures; there is no
   moderation or reporting mechanism now. Domestic models may refuse sensitive text.
3. **Generative-AI rules.** Apply when serving the mainland public. User-supplied keys help
   (you are not reselling model access), but regulators may not accept that distinction.
   Lower risk if serving overseas users from an overseas server.
4. **Personal information.** Uploads may contain personal data; files go to third-party
   (possibly overseas) vendors, which is a cross-border provision needing notice and
   consent. Need a real privacy policy; check IP logging (Caddy) and the 6-month log rule.
5. **Licensing / filing.** Overseas hosting avoids ICP, but mainland access may be slow or
   blocked. Charging mainland users may need a commercial ICP license and foreign-investment
   limits may apply.
6. **Contract / consumer.** No terms, disclaimers or refund rules. Consumer-protection law
   limits exclusion clauses.
7. **Third-party licences (minor).** Check the licence of the CJK font embedded in output
   PDFs (some forbid embedding or commercial use). OpenCV and fonttools are fine.

## 4. Can a policy remove the risk?

No; it lowers risk and sets up the safe-harbour argument.

- **Policies can:** establish notice-and-takedown, document that you asked users to confirm
  their rights, allocate responsibility, meet the privacy notice duty, cap liability for
  quality complaints.
- **Policies cannot:** bind rights holders or regulators; launder a service that is
  obviously used for infringement (marketing and product design matter more than clauses);
  exclude your own main liability to consumers (Civil Code art. 497); replace real
  processes. An unstaffed takedown promise is evidence of knowledge.

### Plan

1. Five documents: terms of use, privacy policy, copyright takedown procedure, upload-time
   rights confirmation (checkbox), acceptable-use policy.
2. Back them with real processes: a monitored takedown mailbox with a log; deletion by job
   (`DELETE /api/jobs/{id}` already exists); store the checkbox time and IP.
3. Marketing words: "translate documents, papers and material you have the right to use",
   not "translate any ebook".
4. Product design: delete after one download; no library, sharing links or search; keep
   users supplying their own key.
5. Have a licensed lawyer review the takedown flow and cross-border data parts.

### Implementation ideas (not done yet)

- Pages `/terms`, `/privacy`, `/takedown` in Chinese and English.
- Rights-confirmation checkbox before upload, recorded in job metadata.
- Privacy text stating files are sent to the selected supplier.
- Update the safety checklist in `docs/DEPLOY.md`.

## 5. Open questions (answers change the advice)

1. Will it charge? How (subscription, per page, free)?
2. Are the main users in mainland China or overseas?
3. Is the operator an individual or a company, and where located?
4. Positioning: "translate ebooks" or "translate your own documents/papers"? The latter is
   much lower risk.
