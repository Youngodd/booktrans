const $ = (id) => document.getElementById(id);
const KEY_PAGES = {
  api: "https://console.anthropic.com/settings/keys",
  qwen: "https://bailian.console.aliyun.com/?apiKey=1",
  "qwen-intl": "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key",
  deepseek: "https://platform.deepseek.com/api_keys",
};

let est = {}, defaultLimit = 10, models = {}, prefs = {};
let token = "", job = null, timer = null, provider = "", savedPath = "", bridge = null, hasKey = false, keyHint = "";

// the shell opens the page as /#token=...; keep the token in memory only
const m = location.hash.match(/token=([^&]+)/);
if (m) token = decodeURIComponent(m[1]);
history.replaceState(null, "", location.pathname);
// the language switch carries the token to the other page, which keeps it in memory the same way
$("lang-switch").href += token ? "#token=" + encodeURIComponent(token) : "";

function show(id, on) { $(id).classList.toggle("hidden", !on); }

async function api(path, opts = {}) {
  const r = await fetch(path, Object.assign({}, opts, { headers: Object.assign({ "X-Booktrans-Token": token }, opts.headers || {}) }));
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || ("Error " + r.status));
  return body;
}
const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function waitForBridge() {  // pywebview injects window.pywebview.api; in a plain browser there is none
  return new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
    window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
    setTimeout(() => resolve(null), 1500);
  });
}

/* ---------- key: first run and settings ---------- */
function updateKeyForm() {
  const p = $("provider").value;
  $("key").placeholder = p === "api" ? "sk-ant-…" : "sk-…";
}
$("provider").addEventListener("change", updateKeyForm);
$("keyhelp").onclick = (e) => {
  e.preventDefault();
  const url = KEY_PAGES[$("provider").value];
  if (bridge) bridge.open_url(url); else window.open(url, "_blank", "noopener");
};

const zhSystem = /^zh(-CN|-Hans)?$/i.test(navigator.language || "");  // Anthropic is not reachable from mainland China
function updateKeyPanel(first) {
  if (!provider && zhSystem) provider = "qwen";
  $("key-title").textContent = first ? T.keyTitleFirst : T.keyTitle;
  show("first-run-note", first);
  show("btn-delkey", hasKey);
  if (provider) $("provider").value = provider;
  updateKeyForm(); $("keymsg").textContent = "";
  $("keyhint").textContent = keyHint ? T.storedKey(keyHint) : "";
  show("keyhint", !!(hasKey && keyHint));
}
function openKeyPanel(first) { updateKeyPanel(first); if (!first) $("step-key").scrollIntoView(); }
$("btn-settings").onclick = () => openKeyPanel(false);
$("btn-usingkey").onclick = () => openKeyPanel(!hasKey);
$("btn-changekey").onclick = () => openKeyPanel(!hasKey);

$("btn-savekey").onclick = async () => {
  const p = $("provider").value, k = $("key").value.trim();
  $("keymsg").className = "msg"; $("keymsg").textContent = T.checking;
  $("btn-savekey").disabled = true;
  try {
    let r;
    if (!k) { r = { ok: false, error: T.enterKey }; }
    else if (bridge) { try { r = await bridge.save_key(p, k); } catch (e) { r = { ok: false, error: T.keyFailed }; } }
    else { try { await api("/api/key", json("PUT", { api_key: k, provider: p })); r = { ok: true }; }
           catch (e) { r = { ok: false, error: e.message }; } }
    if (!r.ok) {
      $("keymsg").className = "msg err";
      $("keymsg").textContent = r.status === 401 ? T.keyRejected
        : r.status === 502 ? T.providerUnreachable
        : (r.error || T.keyFailed);
      return;
    }
    $("key").value = ""; hasKey = true; provider = p; keyHint = "…" + k.slice(-4);
    updateKeyPanel(false); updateUsing();
    $("keymsg").className = "msg done"; $("keymsg").textContent = T.keySaved;
  } finally { $("btn-savekey").disabled = false; }
};

$("btn-delkey").onclick = async () => {
  if (bridge) await bridge.delete_key(); else await api("/api/key", { method: "DELETE" });
  hasKey = false; keyHint = ""; updateKeyPanel(true);
};

/* ---------- model pickers ---------- */
const CUSTOM = "__custom__";
function fillPicker(sel, custom, ids, def, saved) {  // ids: the short list, default first; saved: "" means the default
  sel.innerHTML = "";
  for (const id of ids) sel.add(new Option(id + (id === def ? " " + T.modelDefault : ""), id));
  sel.add(new Option(T.modelCustom, CUSTOM));
  const known = !saved || ids.includes(saved);
  sel.value = !saved ? (def || CUSTOM) : known ? saved : CUSTOM;
  custom.value = known ? "" : saved;
  show(custom.id, sel.value === CUSTOM);
}
function pickedModel(sel, custom, def) {  // "" when the provider's default is chosen
  const v = sel.value === CUSTOM ? custom.value.trim() : sel.value;
  return v === def ? "" : v;
}
function currentModels() {
  const c = models[provider] || {};
  const model = pickedModel($("model"), $("model-custom"), c.model);
  const ocrModel = c.ocr_shared || !c.vision ? "" : pickedModel($("ocr-model"), $("ocr-model-custom"), c.vision);
  return { model, ocr_model: ocrModel };
}
function updateOcrPicker() {
  const c = models[provider] || {}, sel = $("ocr-model"), usable = !!c.vision && !c.ocr_shared;
  sel.disabled = $("ocr-model-custom").disabled = !usable || !$("ocr").checked;
  for (const id of ["ocr-model-label", "ocr-model"]) show(id, !!c.vision);  // no OCR model to pick: only the hint below says so
  if (!c.vision) show("ocr-model-custom", false);
  $("model-hint").textContent = c.ocr_shared ? T.ocrShared(currentModels().model || c.model)
    : !c.vision ? T.ocrNoVision : !$("ocr").checked ? T.ocrOff : "";
}
function fillPickers() {  // the choices kept for this provider, else its defaults
  const c = models[provider]; if (!c) return;
  const saved = prefs[provider] || {};
  fillPicker($("model"), $("model-custom"), c.models, c.model, saved.model || "");
  fillPicker($("ocr-model"), $("ocr-model-custom"), c.ocr_shared ? [] : c.vision_models, c.vision, saved.ocr_model || "");
  if (!c.vision) {  // no model reads scanned pages: say so in the box, not "Custom…" with an empty field
    const sel = $("ocr-model"); sel.innerHTML = "";
    sel.add(new Option(T.ocrNoVision.replace(/[。.]$/, ""), "")); sel.value = "";
    show("ocr-model-custom", false);
  }
  updateOcrPicker();
}
function modelsChanged() {
  show("model-custom", $("model").value === CUSTOM); show("ocr-model-custom", $("ocr-model").value === CUSTOM);
  const m = currentModels(); prefs[provider] = m;
  if (bridge) bridge.set_models(provider, m.model, m.ocr_model).catch(() => {});
  updateOcrPicker(); updateEstimate();
}
for (const id of ["model", "ocr-model"]) $(id).addEventListener("change", modelsChanged);
for (const id of ["model-custom", "ocr-model-custom"]) $(id).addEventListener("input", modelsChanged);
$("ocr").addEventListener("change", () => { updateOcrPicker(); updateEstimate(); });

function updateUsing() {
  $("using").textContent = T.using(T.providers[provider] || provider);
  $("ocr").disabled = !(models[provider] || {}).vision;  // e.g. DeepSeek has no vision model
  if ($("ocr").disabled) $("ocr").checked = false;
  fillPickers();
  if (job) updateEstimate();
}

/* ---------- upload ---------- */
function setBook(j) {
  job = j;
  $("bookinfo").textContent = T.bookInfo(j.filename, j.pages_total);
  showDetected(j);
  updateEstimate(); show("step-setup", true);
}
function pageCount() {
  const total = job.pages_total, s = $("pages").value.trim();
  if (!s) return total;
  const mm = s.match(/^(\d+)(?:\s*-\s*(\d+))?$/);
  if (!mm) return total;
  return Math.max(Math.min(+(mm[2] || mm[1]), total) - Math.max(+mm[1], 1) + 1, 0);
}
function limitValue() {  // yuan; null when the box does not hold a number
  const t = $("limit").value.trim();
  if (t === "") return defaultLimit;
  const v = Number(t);
  return Number.isFinite(v) && v >= 0 ? v : null;
}
function updateEstimate() {
  if (!job) return;
  const per = est[provider], n = pageCount();
  if (!per) { $("estimate").textContent = ""; return; }
  const cost = n * per, lim = limitValue(), c = models[provider] || {}, m = currentModels();
  const approx = !!(m.model || (m.ocr_model && $("ocr").checked));  // not the model the rate was written for
  $("estimate").textContent = T.estimate(n, cost, provider === "api", !!(lim && cost > lim), approx);
}
$("pages").addEventListener("input", updateEstimate);
$("limit").addEventListener("input", updateEstimate);

function showFileName() {  // Chinese pages: the visible name beside the button (English pages have none)
  const n = $("filename"); if (n) n.textContent = ($("file").files[0] || {}).name || n.dataset.empty;
}
$("file").addEventListener("change", () => {
  showFileName();
  const f = $("file").files[0];
  if (!f) return;
  clearSaved();
  $("upmsg").textContent = ""; $("upmsg").className = "msg";
  show("upbar", true); $("upbar").firstElementChild.style.width = "0";
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  xhr.setRequestHeader("X-Booktrans-Token", token);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) $("upbar").firstElementChild.style.width = (100 * e.loaded / e.total) + "%"; };
  xhr.onload = () => {
    show("upbar", false);
    let body = {}; try { body = JSON.parse(xhr.responseText); } catch (e) {}
    if (xhr.status !== 200) { $("upmsg").className = "msg err"; $("upmsg").textContent = body.detail || T.uploadFailed; return; }
    show("step-run", false); show("step-names", false); setBook(body);
  };
  xhr.onerror = () => { show("upbar", false); $("upmsg").className = "msg err"; $("upmsg").textContent = T.readFailed; };
  const fd = new FormData(); fd.append("file", f); xhr.send(fd);
});

/* ---------- glossary review ---------- */
const SKIP_LABEL = $("btn-names-skip").textContent;  // "Skip" before translating, "Close" when reviewing
function fillNames(entries) {
  $("names").innerHTML = "";
  for (const e of entries) {
    const tr = document.createElement("tr"), a = document.createElement("td"), b = document.createElement("td"), inp = document.createElement("input");
    a.textContent = e.term; inp.type = "text"; inp.value = e.zh; inp.dataset.term = e.term; b.appendChild(inp);
    tr.append(a, b); $("names").appendChild(tr);
  }
}
function namesMsg(text, err) { $("namesmsg").className = "msg" + (err ? " err" : ""); $("namesmsg").textContent = text; }
async function saveNames() {  // the table as the user left it becomes the glossary
  const entries = {}; document.querySelectorAll("#names input").forEach((i) => { entries[i.dataset.term] = i.value; });
  await api("/api/jobs/" + job.id + "/glossary", json("PUT", { entries }));
}
function glossaryFileName() {
  return (job.filename || "book").replace(/\.[^.]*$/, "") + "_glossary_" + ($("target").value || "zh-CN") + ".txt";
}
$("btn-names-download").onclick = async () => {  // save the glossary as a text file the user can edit
  try {
    await saveNames();
    if (bridge && bridge.save_glossary) {
      const r = await bridge.save_glossary(job.id, glossaryFileName());
      if (r.ok) namesMsg(T.namesSaved(r.path)); else if (r.error) namesMsg(r.error, true);
    } else {
      const r = await fetch("/api/jobs/" + job.id + "/glossary/download", { headers: { "X-Booktrans-Token": token } });
      if (!r.ok) { namesMsg((await r.json()).detail || "", true); return; }
      const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = glossaryFileName(); a.click();
    }
  } catch (e) { namesMsg(e.message, true); }
};
$("btn-names-import").onclick = () => $("names-file").click();
$("names-file").onchange = async () => {  // an edited glossary file replaces the renderings
  const f = $("names-file").files[0]; $("names-file").value = "";
  if (!f) return;
  try {
    const r = await api("/api/jobs/" + job.id + "/glossary/import", json("POST", { text: await f.text() }));
    fillNames((await api("/api/jobs/" + job.id + "/glossary")).entries);
    applyPages = 0; $("btn-names-apply").textContent = T.namesApply;
    namesMsg(T.importedOk(r.entries));
  } catch (e) { namesMsg(e.message, true); }
};
let applyPages = 0;  // pages the last check found; set once the user has seen the cost
$("names").oninput = () => { applyPages = 0; $("btn-names-apply").textContent = T.namesApply; };
$("btn-names-apply").onclick = async () => {
  if (applyPages) { applyPages = 0; show("step-names", false); begin(!!job.preview, { refresh_glossary: true }); return; }
  try {
    await saveNames();
    const ch = await api("/api/jobs/" + job.id + "/glossary/changes");
    if (!ch.pages) { namesMsg(T.noChanges); return; }
    applyPages = ch.pages;
    namesMsg(T.applyConfirm(ch.pages, ch.translated, ch.est_cny));
    $("btn-names-apply").textContent = T.applyGo(ch.pages);
  } catch (e) { namesMsg(e.message, true); }
};
async function reviewDone() {  // after a translation: check the names it used and apply fixes to the pages
  show("step-setup", false); show("step-names", true);
  for (const id of ["btn-names-go", "btn-names-skip"]) show(id, false);
  show("btn-names-download", true); show("btn-names-import", true); show("btn-names-apply", true);
  applyPages = 0; $("btn-names-apply").textContent = T.namesApply;
  $("names").innerHTML = ""; namesMsg(T.namesReviewIntro);
  try { fillNames((await api("/api/jobs/" + job.id + "/glossary")).entries); } catch (e) { namesMsg(e.message, true); }
  $("btn-names-skip").textContent = T.namesClose; show("btn-names-skip", true);
  $("btn-names-skip").onclick = () => show("step-names", false);
}
$("btn-names-review").onclick = reviewDone;
async function reviewNames(preview) {
  show("step-setup", false); show("step-names", true);
  $("names").innerHTML = ""; show("btn-names-go", false); show("btn-names-skip", false);
  for (const id of ["btn-names-download", "btn-names-import", "btn-names-apply"]) show(id, false);
  $("btn-names-skip").textContent = SKIP_LABEL;
  $("namesmsg").className = "msg"; $("namesmsg").textContent = T.namesCollecting;
  try {
    await api("/api/jobs/" + job.id + "/glossary/draft", json("POST", Object.assign({ pages: $("pages").value, preview, model: currentModels().model }, languageFields())));
    let g;
    do { await new Promise((r) => setTimeout(r, 1500)); g = await api("/api/jobs/" + job.id + "/glossary"); } while (g.state === "building");
    if (g.state === "failed") throw new Error(g.error || "failed");
    $("namesmsg").textContent = g.entries.length ? T.namesIntro : T.namesNone;
    fillNames(g.entries);
    show("btn-names-go", true); show("btn-names-skip", true);
    if (g.entries.length) { show("btn-names-download", true); show("btn-names-import", true); }  // check them before paying for the book
    $("btn-names-go").onclick = async () => {
      try { await saveNames(); } catch (e) { namesMsg(e.message, true); return; }
      show("step-names", false); begin(preview);
    };
    $("btn-names-skip").onclick = () => { show("step-names", false); begin(preview); };
  } catch (e) {
    $("namesmsg").className = "msg err"; $("namesmsg").textContent = e.message;
    show("btn-names-skip", true); $("btn-names-skip").onclick = () => { show("step-names", false); show("step-setup", true); };
  }
}

/* ---------- start, progress, cancel ---------- */
function clearSaved() { savedPath = ""; $("savemsg").textContent = ""; $("savemsg").className = "msg"; show("btn-reveal", false); }
async function start(preview) {
  $("startmsg").textContent = ""; clearSaved();
  if (!hasKey) { openKeyPanel(true); return; }
  if (!$("rights").checked) { $("startmsg").textContent = T.tickBox; return; }
  if (!(models[provider] || {}).model && !currentModels().model) { $("startmsg").textContent = T.modelRequired; return; }
  if ($("review").checked) return reviewNames(preview);
  begin(preview);
}
async function begin(preview, extra = {}) {
  const lim = limitValue();
  if (lim === null) { show("step-setup", true); $("startmsg").textContent = T.limitNumber; return; }
  try {
    const j = await api("/api/jobs/" + job.id + "/start", json("POST", Object.assign({ provider, pages: $("pages").value, preview, ocr: $("ocr").checked, auto_glossary: true, spend_limit: lim,
      model: currentModels().model, ocr_model: $("ocr").checked ? currentModels().ocr_model : "" }, languageFields(), extra)));
    render(j); poll();
  } catch (e) { show("step-setup", true); $("startmsg").textContent = e.message; }
}
$("btn-start").onclick = () => start(false);
$("btn-preview").onclick = () => start(true);
$("btn-continue").onclick = () => begin(!!job.preview);
$("btn-raise").onclick = () => {
  const t = $("newlimit").value.trim(), v = Number(t);
  if (t === "" || !Number.isFinite(v) || v < 0 || (v > 0 && v <= (job.spent_cny || 0))) {
    $("decision-err").textContent = T.raiseErr((job.spent_cny || 0).toFixed(2));
    return;
  }
  $("decision-err").textContent = ""; $("limit").value = String(v); begin(!!job.preview);
};
$("btn-finish-partial").onclick = () => begin(!!job.preview, { only_cached: true });
$("btn-stop").onclick = async () => { try { render(await api("/api/jobs/" + job.id + "/cancel", { method: "POST" })); } catch (e) { $("decision-err").textContent = e.message; } };
$("btn-cancel").onclick = async () => { $("btn-cancel").disabled = true; try { await api("/api/jobs/" + job.id + "/cancel", { method: "POST" }); } catch (e) {} };

function failureText(j) {  // what happened and what to do, in this page's language, plus the short detail
  const advice = T.errors[j.error_code];
  return advice ? advice + (j.error_detail ? " (" + T.detail + j.error_detail + ")" : "") : (j.error || "");
}
function restoreForm(j) {  // put back what the book was submitted with, so Continue sends what the summary says
  $("source").value = j.source || "auto"; $("target").value = j.target || $("target").value;
  $("output-mode").value = j.output_mode || "bilingual";
  if (!j.preview) $("pages").value = j.range && j.range !== "1-" + j.pages_total ? j.range : "";
  if (j.spend_limit !== undefined) $("limit").value = String(j.spend_limit);
  if (j.provider === provider) {  // the saved key may belong to another provider by now
    $("ocr").checked = !!j.ocr && !$("ocr").disabled;
    prefs[provider] = { model: j.model || "", ocr_model: j.ocr_model || "" };
    fillPickers();
  }
  updateEstimate();
}
let restoredFor = "";  // the job whose settings were last put back into the form
function render(j) {
  const before = job && job.state;
  job = Object.assign(job || {}, j);
  show("step-run", true); fillRunInfo(job);
  const resting = j.state === "paused" || j.state === "failed";
  // the form is hidden while the book runs, so fill it from the saved job: the first time this job is
  // shown (a reopened app) and whenever it stops for the user; Continue and Raise send these values
  if ((resting && before !== j.state) || (j.state !== "uploaded" && restoredFor !== j.id)) { restoreForm(job); restoredFor = j.id; }
  const active = j.state === "queued" || j.state === "running";
  $("bar").style.width = (j.state === "done" ? 100 : (j.total ? 100 * j.done / j.total : 0)) + "%";
  $("runerr").textContent = j.state === "failed" ? failureText(j) : "";
  $("stage").className = "msg" + (j.state === "done" ? " done" : "");
  const spent = j.spent_cny ? T.spent(j.spent_cny.toFixed(2)) : "";
  show("decision", j.state === "needs_decision");
  if (j.state === "needs_decision") {
    $("decision-text").textContent = T.decision((j.spent_cny || 0).toFixed(2), (j.spend_limit || 0).toFixed(2), j.done, j.total,
                                               j.est_rest_cny ? j.est_rest_cny.toFixed(2) : "");
    $("newlimit").value = String(Math.ceil((j.spent_cny || 0) + 10)); $("decision-err").textContent = "";
  }
  $("stage").textContent = j.state === "done" ? (j.partial ? T.donePartial : j.preview ? T.donePreview : T.done) + spent
    : j.state === "needs_decision" ? T.pausedLimit + spent
    : j.state === "failed" ? T.failed
    : j.state === "paused" ? T.paused
    : (T.stages[j.stage] || j.stage) + (j.total ? " " + j.done + "/" + j.total : "");
  show("btn-cancel", active); $("btn-cancel").disabled = false;
  show("btn-continue", j.state === "paused" || j.state === "failed");
  show("btn-changekey", j.state === "failed");  // a failed book is often a key problem: one click to the key
  show("btn-names-review", j.state === "done");
  show("btn-save", j.state === "done"); show("btn-reveal", !!savedPath && j.state === "done");
  show("btn-again", !active); show("btn-delete", !active);
  show("step-setup", resting);  // while it runs only the summary shows; the form returns when it stops for the user to fix
  if (resting && before !== j.state) $("step-run").scrollIntoView({ block: "nearest" });  // the error and Continue stay in view, the form is just above
  if (!active && job.pages_total) updateEstimate();
}
function poll() {
  clearInterval(timer);
  timer = setInterval(async () => {
    try {
      const j = await api("/api/jobs/" + job.id); render(j);
      if (j.state !== "queued" && j.state !== "running") clearInterval(timer);
    } catch (e) { clearInterval(timer); $("runerr").textContent = e.message; }
  }, 1500);
}
$("btn-again").onclick = () => { show("step-setup", true); $("startmsg").textContent = ""; clearSaved(); };
$("btn-delete").onclick = async () => {
  try { await api("/api/jobs/" + job.id, { method: "DELETE" }); } catch (e) {}
  job = null; clearSaved(); show("step-setup", false); show("step-run", false); $("file").value = ""; showFileName();
};

/* ---------- save the PDF where the user chooses ---------- */
$("btn-save").onclick = async () => {
  const name = downloadName(job);
  $("savemsg").className = "msg";
  try {
    if (bridge) {
      const r = await bridge.save_pdf(job.id, name);
      if (!r.ok) return;
      savedPath = r.path; $("savemsg").textContent = T.savedTo(r.path); show("btn-reveal", true);
    } else {
      const r = await fetch("/api/jobs/" + job.id + "/download", { headers: { "X-Booktrans-Token": token } });
      const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click();
    }
  } catch (e) { $("savemsg").className = "msg err"; $("savemsg").textContent = e.message; }
};
$("btn-reveal").onclick = () => { if (bridge && savedPath) bridge.reveal(savedPath); };

/* ---------- start-up ---------- */
(async function init() {
  bridge = await waitForBridge();
  try {
    let cfg = await api("/api/config");
    if (!cfg.has_key && bridge) {
      const s = await bridge.has_key();
      if (s.has_key) { keyHint = s.hint || ""; await bridge.use_stored_key(); cfg = await api("/api/config"); }
    }
    if (bridge) { try { prefs = await bridge.get_models(); } catch (e) {} }
    hasKey = cfg.has_key; provider = cfg.provider || "";
    est = cfg.est_cny_per_page || {}; models = cfg.models || {}; defaultLimit = cfg.default_spend_limit ?? 10;
    if (!$("limit").value) $("limit").value = String(defaultLimit);
    initLanguages(cfg.languages, cfg.default_target);
  } catch (e) { $("upmsg").className = "msg err"; $("upmsg").textContent = T.cannotReach; return; }
  updateKeyPanel(!hasKey); if (hasKey) updateUsing();
  try {  // reopen the newest book, if any
    const jobs = await api("/api/jobs");
    if (jobs.length) {
      const j = jobs[0]; setBook(j);
      if (j.state !== "uploaded") { render(j); if (j.state === "queued" || j.state === "running") poll(); }
    }
  } catch (e) {}
})();
