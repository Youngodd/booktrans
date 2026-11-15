/* Language and output pickers shared by the web and desktop pages.
   The list comes from /api/config (languages.LANGUAGES on the server), so there is one list. */
let LANG_LIST = [], LAST_JOB = null;

function langLabel(l) { return l.native === l.name ? l.name : l.native + " (" + l.name + ")"; }
function langName(code) { const l = LANG_LIST.find((x) => x.code === code); return l ? langLabel(l) : ""; }

/* English pages default to English, Chinese pages to the server default (Simplified Chinese). */
function pageDefaultTarget(serverDefault) {
  return (document.documentElement.lang || "").toLowerCase().startsWith("en") ? "en" : serverDefault;
}

/* A book in the chosen target language gets the other interface language as target instead. */
function avoidSameLanguage(code) {
  const tgt = document.getElementById("target");
  if (code && tgt.value === code) tgt.value = code === "en" ? "zh-CN" : "en";
}

function initLanguages(list, defaultTarget) {
  LANG_LIST = list || [];
  const src = document.getElementById("source"), tgt = document.getElementById("target");
  src.innerHTML = ""; tgt.innerHTML = "";
  const auto = document.createElement("option"); auto.value = "auto"; auto.textContent = T.autoDetect; src.appendChild(auto);
  for (const l of LANG_LIST) {
    for (const sel of [src, tgt]) {
      const o = document.createElement("option"); o.value = l.code; o.textContent = langLabel(l); sel.appendChild(o);
    }
  }
  tgt.value = pageDefaultTarget(defaultTarget);
  if (LAST_JOB) showDetected(LAST_JOB);  // the book was shown before the list arrived
}

/* After a book is uploaded: tell the user which language was detected (they can still override). */
function showDetected(job) {
  LAST_JOB = job;
  const hint = document.getElementById("detected"), src = document.getElementById("source");
  const name = job && job.detected_language ? langName(job.detected_language) : "";
  src.value = "auto";
  avoidSameLanguage(job && job.detected_language);
  hint.textContent = name ? T.detected(name) : T.notDetected;
  showRecommended(job);
}

/* Suggested settings for the uploaded book (job.recommended): the controls are filled in once, right
   after the upload, and the reasons are listed. Nothing is applied later, so a choice the user has
   made is never overwritten. */
const REC_ZH = document.documentElement.lang.startsWith("zh");
const REC_TEXT = REC_ZH
  ? { title: "建议的设置（都可以修改）：", source: "书的语言", target: "翻译成", ocr: "OCR", output_format: "输出格式",
      output_mode: "输出内容", pages: "页码范围", review_names: "先核对名称", on: "开启", off: "不需要",
      bilingual: "双语对照", "target-only": "仅译文" }
  : { title: "Suggested settings (you can change any of them):", source: "Book language", target: "Translate into",
      ocr: "OCR", output_format: "Output format", output_mode: "Output", pages: "Page range",
      review_names: "Review names first", on: "on", off: "not needed", bilingual: "bilingual", "target-only": "translation only" };
let REC_APPLIED = "";
function showRecommended(job) {
  const box = document.getElementById("recommended"), rec = job && job.recommended;
  if (!box) return;
  const s = (rec && rec.settings) || {}, why = (rec && rec.reasons) || {};
  const names = Object.keys(s);
  box.classList.toggle("hidden", !names.length || job.state !== "uploaded");
  if (!names.length || job.state !== "uploaded") return;
  const el = (id) => document.getElementById(id);
  if (REC_APPLIED !== job.id) {  // once per book
    REC_APPLIED = job.id;
    const pick = (id, v) => { const c = el(id); if (c && [...c.options].some((o) => o.value === v)) c.value = v; };
    if (s.target) pick("target", s.target);
    if (s.output_format) pick("output-format", s.output_format);
    if (s.output_mode) pick("output-mode", s.output_mode);
    if (s.pages && el("pages") && !el("pages").value.trim()) el("pages").value = s.pages;
    if ("ocr" in s && el("ocr") && !el("ocr").disabled) el("ocr").checked = !!s.ocr;
    if (s.review_names && el("review")) el("review").checked = true;
    for (const id of ["pages", "ocr", "output-format"]) if (el(id)) el(id).dispatchEvent(new Event(id === "pages" ? "input" : "change"));
  }
  const shown = (k, v) => k === "source" || k === "target" ? langName(v)
    : typeof v === "boolean" ? (v ? REC_TEXT.on : REC_TEXT.off)
    : k === "output_format" ? v.toUpperCase() : REC_TEXT[v] || v;
  box.textContent = "";
  const head = document.createElement("strong"); head.textContent = REC_TEXT.title; box.appendChild(head);
  const list = document.createElement("ul");
  for (const k of names) {
    const li = document.createElement("li"), r = why[k] || {};
    li.textContent = (REC_TEXT[k] || k) + ": " + shown(k, s[k]) + " — " + ((REC_ZH ? r.zh : r.en) || "");
    list.appendChild(li);
  }
  box.appendChild(list);
}

function languageFields() {
  return { source: document.getElementById("source").value, target: document.getElementById("target").value,
           output_mode: document.getElementById("output-mode").value,
           output_format: document.getElementById("output-format").value };
}

/* The read-only summary of what a book was submitted with, shown on the progress card so the
   settings can be hidden while it runs. Two lines: the book, and how it is translated.
   The API key is never part of it; the provider is named, nothing more. */
function langShort(code) {  // one name, in the page's language: "French" on an English page, "法语"-style natives on Chinese
  const l = LANG_LIST.find((x) => x.code === code);
  if (!l) return "";
  return (document.documentElement.lang || "").toLowerCase().startsWith("zh") ? l.native : l.name;
}
function runSummary(j) {
  const total = j.pages_total || 0, r = j.range || "";
  const whole = !r || r === "1-" + total;
  const range = j.preview ? T.sumPreview(r) : whole ? "" : T.sumRange(r.replace("-", "–"));
  const book = [j.filename || "", total ? T.sumPages(total) : "", range].filter(Boolean).join(" · ");
  const src = !j.source || j.source === "auto" ? (j.detected_language ? langShort(j.detected_language) : T.autoDetect) : langShort(j.source);
  const tgt = langShort(j.target);
  const prov = (T.providers || {})[j.provider] || j.provider || "";
  const how = [src && tgt ? src + " → " + tgt : tgt, j.output_mode === "target-only" ? T.sumTargetOnly : T.sumBilingual,
               [prov, j.model].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
  return { book, how };
}
function fillRunInfo(j) {
  const s = runSummary(j), box = document.getElementById("runinfo");
  document.getElementById("run-book").textContent = s.book;
  document.getElementById("run-set").textContent = s.how;
  box.classList.toggle("hidden", !(j && j.filename && j.state && j.state !== "uploaded"));
}

function downloadName(job) {
  if (job.download_name) return job.download_name;  // the server knows the format (Markdown with pictures is a zip)
  const stem = (job.filename || "book").replace(/\.[^.]+$/, "");
  return stem + "_" + (job.output_mode === "target-only" ? job.target || "translation" : "bilingual") + "." + (job.output_format || "pdf");
}
