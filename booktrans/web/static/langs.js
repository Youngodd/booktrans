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
}

function languageFields() {
  return { source: document.getElementById("source").value, target: document.getElementById("target").value,
           output_mode: document.getElementById("output-mode").value };
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
  const stem = (job.filename || "book").replace(/\.[^.]+$/, "");
  return stem + "_" + (job.output_mode === "target-only" ? job.target || "translation" : "bilingual") + ".pdf";
}
