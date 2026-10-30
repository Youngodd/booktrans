const $ = (id) => document.getElementById(id);
const KEY_PAGES = {
  api: "https://console.anthropic.com/settings/keys",
  qwen: "https://bailian.console.aliyun.com/?apiKey=1",
  "qwen-intl": "https://modelstudio.console.alibabacloud.com/?tab=playground#/api-key",
  deepseek: "https://platform.deepseek.com/api_keys",
};

let est = {}, defaultLimit = 10;
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
function openKeyPanel(first) {
  if (!provider && zhSystem) provider = "qwen";
  $("key-title").textContent = first ? T.keyTitleFirst : T.keyTitle;
  show("first-run-note", first);
  show("btn-delkey", hasKey); show("btn-closekey", hasKey);
  if (provider) $("provider").value = provider;
  updateKeyForm(); $("keymsg").textContent = "";
  $("keyhint").textContent = keyHint ? T.storedKey(keyHint) : "";
  show("keyhint", !!(hasKey && keyHint));
  show("step-key", true);
  if (!first) $("step-key").scrollIntoView();
}
$("btn-saveproxy").onclick = async () => {
  const url = $("proxy").value.trim();
  $("proxymsg").className = "msg";
  let r;
  if (bridge) r = await bridge.set_proxy(url);
  else { try { r = Object.assign({ ok: true }, await api("/api/proxy", json("PUT", { url }))); } catch (e) { r = { ok: false, error: e.message }; } }
  $("proxymsg").className = "msg" + (r.ok ? " done" : " err");
  $("proxymsg").textContent = r.ok ? (r.proxy ? T.proxySaved(r.proxy) : T.proxyCleared) : (r.error || T.proxyFailed);
  if (r.ok) $("proxy").value = "";
  if (r.ok) $("proxy").placeholder = r.proxy || "http://127.0.0.1:7890";
};
$("btn-settings").onclick = () => openKeyPanel(false);
$("btn-usingkey").onclick = () => openKeyPanel(!hasKey);
$("btn-changekey").onclick = () => openKeyPanel(!hasKey);
$("btn-closekey").onclick = () => show("step-key", false);

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
    show("step-key", false); updateUsing();
  } finally { $("btn-savekey").disabled = false; }
};

$("btn-delkey").onclick = async () => {
  if (bridge) await bridge.delete_key(); else await api("/api/key", { method: "DELETE" });
  hasKey = false; keyHint = ""; openKeyPanel(true);
};

function updateUsing() {
  $("using").textContent = T.using(T.providers[provider] || provider);
  $("ocr").disabled = provider === "deepseek";
  if ($("ocr").disabled) $("ocr").checked = false;
  if (job) updateEstimate();
}

/* ---------- upload ---------- */
function setBook(j) {
  job = j;
  $("bookinfo").textContent = T.bookInfo(j.filename, j.pages_total);
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
  const cost = n * per, lim = limitValue();
  $("estimate").textContent = T.estimate(n, cost, provider === "api", !!(lim && cost > lim));
}
$("pages").addEventListener("input", updateEstimate);
$("limit").addEventListener("input", updateEstimate);

$("file").addEventListener("change", () => {
  const f = $("file").files[0];
  if (!f) return;
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
async function reviewNames(preview) {
  show("step-setup", false); show("step-names", true);
  $("names").innerHTML = ""; show("btn-names-go", false); show("btn-names-skip", false);
  $("namesmsg").className = "msg"; $("namesmsg").textContent = T.namesCollecting;
  try {
    await api("/api/jobs/" + job.id + "/glossary/draft", json("POST", { pages: $("pages").value, preview }));
    let g;
    do { await new Promise((r) => setTimeout(r, 1500)); g = await api("/api/jobs/" + job.id + "/glossary"); } while (g.state === "building");
    if (g.state === "failed") throw new Error(g.error || "failed");
    $("namesmsg").textContent = g.entries.length ? T.namesIntro : T.namesNone;
    for (const e of g.entries) {
      const tr = document.createElement("tr"), a = document.createElement("td"), b = document.createElement("td"), inp = document.createElement("input");
      a.textContent = e.term; inp.type = "text"; inp.value = e.zh; inp.dataset.term = e.term; b.appendChild(inp);
      tr.append(a, b); $("names").appendChild(tr);
    }
    show("btn-names-go", true); show("btn-names-skip", true);
    $("btn-names-go").onclick = async () => {
      const entries = {}; document.querySelectorAll("#names input").forEach((i) => { entries[i.dataset.term] = i.value; });
      try { await api("/api/jobs/" + job.id + "/glossary", json("PUT", { entries })); } catch (e) { $("namesmsg").className = "msg err"; $("namesmsg").textContent = e.message; return; }
      show("step-names", false); begin(preview);
    };
    $("btn-names-skip").onclick = () => { show("step-names", false); begin(preview); };
  } catch (e) {
    $("namesmsg").className = "msg err"; $("namesmsg").textContent = e.message;
    show("btn-names-skip", true); $("btn-names-skip").onclick = () => { show("step-names", false); show("step-setup", true); };
  }
}

/* ---------- start, progress, cancel ---------- */
async function start(preview) {
  $("startmsg").textContent = "";
  if (!hasKey) { openKeyPanel(true); return; }
  if (!$("rights").checked) { $("startmsg").textContent = T.tickBox; return; }
  if ($("review").checked) return reviewNames(preview);
  begin(preview);
}
async function begin(preview, extra = {}) {
  const lim = limitValue();
  if (lim === null) { show("step-setup", true); $("startmsg").textContent = T.limitNumber; return; }
  try {
    const j = await api("/api/jobs/" + job.id + "/start", json("POST", Object.assign({ provider, pages: $("pages").value, preview, ocr: $("ocr").checked, auto_glossary: true, spend_limit: lim }, extra)));
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

function render(j) {
  job = Object.assign(job || {}, j);
  show("step-run", true);
  const active = j.state === "queued" || j.state === "running";
  $("bar").style.width = (j.state === "done" ? 100 : (j.total ? 100 * j.done / j.total : 0)) + "%";
  $("runerr").textContent = j.state === "failed" ? j.error : "";
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
  show("btn-save", j.state === "done"); show("btn-reveal", !!savedPath && j.state === "done");
  show("btn-again", !active); show("btn-delete", !active);
  show("step-setup", false);
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
$("btn-again").onclick = () => { show("step-setup", true); $("startmsg").textContent = ""; };
$("btn-delete").onclick = async () => {
  try { await api("/api/jobs/" + job.id, { method: "DELETE" }); } catch (e) {}
  job = null; savedPath = ""; show("step-setup", false); show("step-run", false); $("file").value = "";
};

/* ---------- save the PDF where the user chooses ---------- */
$("btn-save").onclick = async () => {
  const name = (job.filename || "book").replace(/\.[^.]+$/, "") + "_bilingual.pdf";
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
    if (bridge) await bridge.use_stored_proxy();
    let cfg = await api("/api/config");
    if (cfg.proxy) $("proxy").placeholder = cfg.proxy;
    if (!cfg.has_key && bridge) {
      const s = await bridge.has_key();
      if (s.has_key) { keyHint = s.hint || ""; await bridge.use_stored_key(); cfg = await api("/api/config"); }
    }
    hasKey = cfg.has_key; provider = cfg.provider || "";
    est = cfg.est_cny_per_page || {}; defaultLimit = cfg.default_spend_limit ?? 10;
    if (!$("limit").value) $("limit").value = String(defaultLimit);
  } catch (e) { $("upmsg").className = "msg err"; $("upmsg").textContent = T.cannotReach; return; }
  if (hasKey) updateUsing(); else openKeyPanel(true);
  try {  // reopen the newest book, if any
    const jobs = await api("/api/jobs");
    if (jobs.length) {
      const j = jobs[0]; setBook(j);
      if (j.state !== "uploaded") { render(j); if (j.state === "queued" || j.state === "running") poll(); }
    }
  } catch (e) {}
})();
