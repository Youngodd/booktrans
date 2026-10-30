const $ = (id) => document.getElementById(id);
if (location.protocol === "http:" && !["localhost", "127.0.0.1"].includes(location.hostname))
  $("insecure").classList.remove("hidden");
let job = null, timer = null;

function save(id) { try { localStorage.setItem("job", id || ""); } catch (e) {} }
function saved() { try { return localStorage.getItem("job") || ""; } catch (e) { return ""; } }
function show(id, on) { $(id).classList.toggle("hidden", !on); }

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || ("Error " + r.status));
  return body;
}

function setBook(j) {
  job = j;
  $("bookinfo").textContent = T.bookInfo(j.filename, j.pages_total);
  updateEstimate();
  show("step-setup", true);
}

function pageCount() {
  const total = job.pages_total, s = $("pages").value.trim();
  if (!s) return total;
  const m = s.match(/^(\d+)(?:\s*-\s*(\d+))?$/);
  if (!m) return total;
  const a = Math.max(+m[1], 1), b = Math.min(+(m[2] || m[1]), total);
  return Math.max(b - a + 1, 0);
}

function updateEstimate() {
  if (!job) return;
  if ($("provider").value !== "api") {
    $("estimate").textContent = T.estimateOther;
    return;
  }
  const n = pageCount(), c = n * job.est_cost_per_page;
  $("estimate").textContent = T.estimate(n, c.toFixed(2));
}

$("pages").addEventListener("input", updateEstimate);
$("provider").addEventListener("change", () => {
  const p = $("provider").value;
  $("key").placeholder = p === "api" ? "sk-ant-…" : p === "deepseek" ? "sk-…" : "sk-…";
  $("ocr").disabled = p === "deepseek";
  if ($("ocr").disabled) $("ocr").checked = false;
  updateEstimate();
});

$("file").addEventListener("change", () => {
  const f = $("file").files[0];
  if (!f) return;
  $("upmsg").textContent = ""; $("upmsg").className = "msg";
  show("upbar", true); $("upbar").firstElementChild.style.width = "0";
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) $("upbar").firstElementChild.style.width = (100 * e.loaded / e.total) + "%";
  };
  xhr.onload = () => {
    show("upbar", false);
    let body = {}; try { body = JSON.parse(xhr.responseText); } catch (e) {}
    if (xhr.status !== 200) { $("upmsg").className = "msg err"; $("upmsg").textContent = body.detail || T.uploadFailed; return; }
    save(body.id); show("step-run", false); setBook(body);
  };
  xhr.onerror = () => { show("upbar", false); $("upmsg").className = "msg err"; $("upmsg").textContent = T.networkError; };
  const fd = new FormData(); fd.append("file", f); xhr.send(fd);
});

async function start(preview) {
  $("startmsg").textContent = "";
  if (!$("rights").checked) { $("startmsg").textContent = T.tickBox; return; }
  try {
    const j = await api("/api/jobs/" + job.id + "/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: $("key").value, provider: $("provider").value, pages: $("pages").value, preview: preview, ocr: $("ocr").checked }),
    });
    $("key").value = "";  // the server has it; do not leave it in the page
    render(j); poll();
  } catch (e) { $("startmsg").textContent = e.message; }
}
$("btn-start").onclick = () => start(false);
$("btn-preview").onclick = () => start(true);

function render(j) {
  job = Object.assign(job || {}, j);
  show("step-run", true);
  const active = j.state === "queued" || j.state === "running";
  const pct = j.total ? 100 * j.done / j.total : 0;
  $("bar").style.width = (j.state === "done" ? 100 : pct) + "%";
  $("runerr").textContent = j.state === "failed" ? j.error : "";
  const label = T.stages[j.stage] || j.stage;
  $("stage").className = "msg" + (j.state === "done" ? " done" : "");
  $("stage").textContent = j.state === "done"
    ? (j.preview ? T.donePreview : T.done)
    : j.state === "failed" ? T.failed
    : label + (j.total ? " " + j.done + "/" + j.total : "");
  show("download", j.state === "done");
  if (j.state === "done") $("download").href = "/api/jobs/" + j.id + "/download";
  show("btn-again", !active); show("btn-delete", !active);
  show("step-setup", !active);
  if (!active && job.pages_total) updateEstimate();
}

function poll() {
  clearInterval(timer);
  timer = setInterval(async () => {
    try {
      const j = await api("/api/jobs/" + job.id);
      render(j);
      if (j.state !== "queued" && j.state !== "running") clearInterval(timer);
    } catch (e) { clearInterval(timer); $("runerr").textContent = e.message; }
  }, 2000);
}

$("btn-again").onclick = () => { show("step-setup", true); $("startmsg").textContent = ""; };
$("btn-delete").onclick = async () => {
  try { await api("/api/jobs/" + job.id, { method: "DELETE" }); } catch (e) {}
  save(""); job = null; show("step-setup", false); show("step-run", false); $("file").value = "";
};

(async function resume() {
  const id = saved();
  if (!id) return;
  try {
    const j = await api("/api/jobs/" + id);
    setBook(j);
    if (j.state !== "uploaded") { render(j); if (j.state === "queued" || j.state === "running") poll(); }
  } catch (e) { save(""); }
})();
