/* AdvPrint Pro - options page logic (v2.6: print defaults + LAN/PCs + hub settings + token detect) */
const $ = (id) => document.getElementById(id);
let PRINTERS = [];
let QUEUE_TIMER = null;
let LAN_TIMER = null;
let DEBUG_TIMER = null;   // v2.3: Debug tab auto-refresh
let CAPS = null;

function send(m) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(m, (r) => resolve(r || { ok: false, error: "no response" }));
  });
}
function saved(text) {
  $("saveMsg").textContent = text || "Saved";
  setTimeout(() => { $("saveMsg").textContent = ""; }, 2500);
}

/* ---------- tabs (Queue | History | Settings | Debug | LAN | About) ---------- */
function showTab(name) {
  const valid = ["queue", "history", "settings", "debug", "lan", "about"].includes(name)
    ? name : "settings";
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === valid));
  document.querySelectorAll("section.panel").forEach((p) =>
    p.classList.toggle("active", p.id === "panel-" + valid));
  if (valid === "queue") startQueueLoop(); else stopQueueLoop();
  if (valid === "lan") startLanLoop(); else stopLanLoop();
  if (valid === "history") startJobsLoop(); else stopJobsLoop();
  if (valid === "debug") startDebugLoop(); else stopDebugLoop();
}

/* v2.2.1: history auto-refreshes every 8 s while the tab is open, so a
 * stuck "queued" row turns "printed" in front of the user (or shows the
 * real error) instead of looking frozen. */
let JOBS_TIMER = null;
function stopJobsLoop() {
  if (JOBS_TIMER) { clearInterval(JOBS_TIMER); JOBS_TIMER = null; }
}
function startJobsLoop() {
  stopJobsLoop();
  loadJobs();
  JOBS_TIMER = setInterval(loadJobs, 8000);
}

function stopLanLoop() {
  if (LAN_TIMER) { clearInterval(LAN_TIMER); LAN_TIMER = null; }
}
function startLanLoop() {
  stopLanLoop();
  loadLan();
  LAN_TIMER = setInterval(loadLan, 8000);
}

function stopQueueLoop() {
  if (QUEUE_TIMER) { clearInterval(QUEUE_TIMER); QUEUE_TIMER = null; }
}
function startQueueLoop() {
  stopQueueLoop();
  refreshQueue();
  QUEUE_TIMER = setInterval(refreshQueue, 3000);
}

/* default tab: Queue when the queue/jobs hold data, otherwise Settings.
 * #hash links (options.html#api etc.) always win. */
async function pickDefaultTab() {
  const hash = (location.hash || "").replace("#", "");
  if (hash) {
    showTab(hash === "api" ? "about" : hash);
    return;
  }
  try {
    const st = await send({ type: "hubStatus" });
    if (st.ok && (st.pending > 0 || st.paused)) { showTab("queue"); return; }
    const jobs = await send({ type: "hubJobs", limit: 100 });
    const active = (jobs.ok ? jobs.jobs : []).filter(
      (j) => j.status === "queued" || j.status === "printing");
    if (active.length) { showTab("queue"); return; }
  } catch (_) { /* offline -> settings */ }
  showTab("settings");
}

/* ---------- live queue ---------- */
async function refreshQueue() {
  const body = $("queueBody");
  const st = await send({ type: "hubStatus" });
  if (!st.ok) {
    $("qDot").className = "dot offline";
    $("qState").textContent = "Hub offline";
    $("qInfo").textContent = "start it: python advprint.py serve (or AdvPrint Tool > 1)";
    body.innerHTML = '<tr><td colspan="6">Hub offline - nothing to show.</td></tr>';
    $("bQPause").textContent = "Pause";
    return;
  }
  const pausedNow = !!st.paused;
  $("qDot").className = "dot" + (pausedNow ? " paused" : "");
  $("qState").textContent = pausedNow ? "PAUSED" : "Running";
  $("qInfo").textContent = st.pending + " pending · " +
    (st.jobs_today || 0) + " today · hub v" + st.version;
  $("bQPause").textContent = pausedNow ? "Resume" : "Pause";
  // update the tab badge: active queue items
  const jobs = await send({ type: "hubJobs", limit: 100 });
  const active = (jobs.ok ? jobs.jobs : []).filter(
    (j) => j.status === "queued" || j.status === "printing");
  const badge = $("tabQBadge");
  badge.textContent = String(active.length);
  badge.classList.toggle("show", active.length > 0);
  body.innerHTML = "";
  if (!active.length) {
    body.innerHTML = '<tr><td colspan="6">Queue is empty - nothing waiting.</td></tr>';
    return;
  }
  for (const j of active) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${j.id}</td><td>${(j.title || "-").slice(0, 42)}</td>` +
      `<td>${(j.printer || "default").slice(0, 28)}</td><td>${j.kind}</td>` +
      `<td><span class="st ${j.status}">${j.status}</span></td>`;
    const tdBtn = document.createElement("td");
    const bc = document.createElement("button");
    bc.className = "mini danger"; bc.textContent = "Cancel";
    bc.addEventListener("click", async () => {
      await send({ type: "jobAction", id: j.id, action: "cancel" });
      refreshQueue();
    });
    tdBtn.appendChild(bc);
    if (j.status !== "printing") {
      const bs = document.createElement("button");
      bs.className = "mini"; bs.textContent = "Shift to PC";
      bs.title = "Print this job on ANOTHER PC's hub over the LAN";
      bs.addEventListener("click", () => shiftJobPrompt(j.id));
      tdBtn.appendChild(bs);
    }
    tr.appendChild(tdBtn);
    body.appendChild(tr);
  }
}

/* v2.2: shift one job (or the whole queue) to another PC's hub */
async function shiftJobPrompt(id) {
  const t = prompt(
    `Shift job #${id} to which PC?\n` +
    "Enter the OTHER AdvPrint's LAN URL, e.g. http://192.168.0.60:9235",
    $("shiftTarget").value.trim());
  if (!t) return;
  $("shiftTarget").value = t.trim();
  const r = await send({ type: "queueShift", scope: "job", ids: [id],
                         target: t.trim(), targetToken: $("shiftToken").value.trim() });
  alert(r.ok ? r.message || "shifted" : "Shift failed: " + r.error);
  refreshQueue();
}

/* ---------- GitHub update check ---------- */
async function updateCheck() {
  const out = $("updState"), live = $("updLive");
  out.textContent = "checking...";
  live.innerHTML = "";
  let manifestVer = chrome.runtime.getManifest ?
    chrome.runtime.getManifest().version : "2.6.2";   // v2.6.2: never hardcoded
  try {
    const r = await fetch("https://api.github.com/repos/bitdreamit/AdvPrint-Pro/releases/latest",
      { headers: { "Accept": "application/vnd.github+json" } });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    const tag = String(d.tag_name || "").replace(/^v/i, "");
    const url = d.html_url || "https://github.com/bitdreamit/AdvPrint-Pro/releases/latest";
    const num = (s) => (s.match(/\d+/g) || []).slice(0, 3).map(Number);
    const [a = [0, 0, 0], b = [0, 0, 0]] = [num(tag), num(manifestVer)];
    const newer = a.some((v, i) => v > (b[i] || 0));
    if (newer) {
      out.textContent = "";
      live.innerHTML = 'UPDATE AVAILABLE: <b>v' + tag + '</b> (you have v' + manifestVer +
        ') - <a href="' + url + '" target="_blank" rel="noreferrer">download from GitHub</a>';
    } else {
      out.textContent = "up to date (latest release: v" + tag + ")";
    }
  } catch (e) {
    out.textContent = "could not reach GitHub (" + e.message + ")";
  }
}

/* ---------- rules table (v2.0: type glob/regex, title filter, on/off) -- */
function ruleRow(rule) {
  const tr = document.createElement("tr");

  const tdP = document.createElement("td");
  const inP = document.createElement("input");
  inP.type = "text"; inP.value = rule.pattern || "";
  inP.placeholder = "*://example.com/reports/*";
  inP.addEventListener("change", collect);
  tdP.appendChild(inP);

  const tdT = document.createElement("td");
  const selT = document.createElement("select");
  selT.appendChild(new Option("Glob", "glob"));
  selT.appendChild(new Option("Regex", "regex"));
  selT.value = rule.type || "glob";
  selT.title = "Glob = 1.x style wildcards; Regex = v2.0 regular expression";
  selT.addEventListener("change", collect);
  tdT.appendChild(selT);

  const tdTi = document.createElement("td");
  const inTi = document.createElement("input");
  inTi.type = "text"; inTi.value = rule.title || "";
  inTi.placeholder = "invoice?";
  inTi.title = "Only match when the page title contains this text";
  inTi.addEventListener("change", collect);
  tdTi.appendChild(inTi);

  const tdPr = document.createElement("td");
  const sel = document.createElement("select");
  sel.appendChild(new Option("(default printer)", ""));
  sel.appendChild(new Option("File (save as PDF)", "__file__"));
  PRINTERS.forEach((p) => sel.appendChild(new Option(p.name, p.name)));
  sel.value = rule.printer || "";
  sel.addEventListener("change", collect);
  tdPr.appendChild(sel);

  const tdA = document.createElement("td");
  const selA = document.createElement("select");
  [["auto", "Auto (PDF or page)"], ["pdf", "PDF only"], ["page", "Page render"]]
    .forEach(([v, t]) => selA.appendChild(new Option(t, v)));
  selA.value = rule.action || "auto";
  selA.addEventListener("change", collect);
  tdA.appendChild(selA);

  const tdOn = document.createElement("td");
  const onChk = document.createElement("input");
  onChk.type = "checkbox"; onChk.checked = rule.enabled !== false;
  onChk.title = "Per-site on/off switch";
  onChk.addEventListener("change", collect);
  tdOn.appendChild(onChk);

  const tdAuto = document.createElement("td");
  const chk = document.createElement("input");
  chk.type = "checkbox"; chk.checked = !!rule.auto;
  chk.title = "Print automatically when the URL is opened";
  chk.addEventListener("change", collect);
  tdAuto.appendChild(chk);

  const tdX = document.createElement("td");
  const bx = document.createElement("button");
  bx.className = "mini danger"; bx.textContent = "Delete";
  bx.addEventListener("click", () => { tr.remove(); collect(); });
  tdX.appendChild(bx);

  tr.append(tdP, tdT, tdTi, tdPr, tdA, tdOn, tdAuto, tdX);
  return tr;
}

function renderRules(rules) {
  const body = $("rulesBody");
  body.innerHTML = "";
  (rules && rules.length ? rules : []).forEach((r) => body.appendChild(ruleRow(r)));
}

function collect() {
  const rules = [];
  $("rulesBody").querySelectorAll("tr").forEach((tr) => {
    const [p, ty, ti, pr, a, on, auto] =
      tr.querySelectorAll("input, select, select, select, select, input, input");
    if (p.value.trim()) {
      rules.push({ pattern: p.value.trim(), type: ty.value,
                   title: ti.value.trim(), printer: pr.value,
                   action: a.value, enabled: on.checked,
                   auto: auto.checked });
    }
  });
  return rules;
}

/* ---------- v2.2: default print options (stored as cfg.printDefaults) */
function PD() {
  return {
    copies: ($("dCopies").value || "").trim(),
    pagesMode: $("dPagesMode").value,
    pagesCustom: ($("dPagesCustom").value || "").trim(),
    quality: $("dQuality").value,
    qualityCustom: ($("dQualityCustom").value || "").trim(),
    perSheet: $("dPerSheet").value,
    duplex: $("dDuplex").value,
    orient: $("dOrient").value,
    scale: ($("dScale").value || "").trim(),
    margin: ($("dMargin").value || "").trim(),
    paper: $("dPaper").value
  };
}

function applyPrintDefaults(pd) {
  pd = pd || {};
  $("dCopies").value = pd.copies || "";
  $("dPagesMode").value = pd.pagesMode || "";
  $("dPagesCustom").value = pd.pagesCustom || "";
  $("dQuality").value = pd.quality || "";
  $("dQualityCustom").value = pd.qualityCustom || "";
  $("dPerSheet").value = pd.perSheet || "";
  $("dDuplex").value = pd.duplex || "";
  $("dOrient").value = pd.orient || "";
  $("dScale").value = pd.scale || "";
  $("dMargin").value = pd.margin || "";
  $("dPaper").value = pd.paper || "";
}

/* What the hub will actually receive for the current defaults - the same
 * merge logic background.js applies before POST /print. */
function effectiveOptions(pd) {
  pd = pd || PD();
  const o = {};
  if (pd.copies && parseInt(pd.copies, 10) > 1) o.copies = parseInt(pd.copies, 10);
  if (pd.pagesMode === "odd" || pd.pagesMode === "even") o.pages = pd.pagesMode;
  else if (pd.pagesMode === "custom" && pd.pagesCustom) o.pages = pd.pagesCustom;
  if (pd.quality === "custom" && pd.qualityCustom) o.quality = pd.qualityCustom;
  else if (pd.quality) o.quality = pd.quality;
  if (pd.perSheet && parseInt(pd.perSheet, 10) > 1) o.per_sheet = parseInt(pd.perSheet, 10);
  if (pd.duplex) o.duplex = pd.duplex;
  if (pd.orient) o.orientation = pd.orient;
  if (pd.scale && parseInt(pd.scale, 10) !== 100) o.scale_pct = parseInt(pd.scale, 10);
  if (pd.margin) o.margin_mm = parseFloat(pd.margin);
  if (pd.paper) o.paper_size = pd.paper;
  return o;
}

async function refreshCaps() {
  const note = $("capsNote");
  const p = $("defaultPrinter").value;
  if (!p) {
    CAPS = null;
    note.innerHTML = "Using the OS default printer - the hub reports what it supports per job.";
    return;
  }
  const r = await send({ type: "hubCaps", name: p });
  if (!r.ok) {
    CAPS = null;
    note.innerHTML = "Could not read capabilities (hub offline?).";
    return;
  }
  CAPS = r.caps;
  const parts = [];
  parts.push("backend: <b>" + (r.caps.backend || "?") + "</b>");
  if (r.caps.pages) parts.push("odd/even pages: <b>" + (r.caps.pages.odd_even ? "yes" : "no") + "</b>");
  if (r.caps.copies) parts.push("copies: <b>" + r.caps.copies.max + "</b>");
  if (r.caps.per_sheet) parts.push("per-sheet: <b>" +
    (Array.isArray(r.caps.per_sheet) ? r.caps.per_sheet.join("/") : r.caps.per_sheet) + "</b>");
  else parts.push("per-sheet: <b>no (driver)</b>");
  if (r.caps.quality) {
    if (Array.isArray(r.caps.quality)) parts.push("quality: <b>" + r.caps.quality.join("/") + "</b>");
    else parts.push("quality: <b>" + (r.caps.quality.presets || []).join("/") +
                    "</b>, dpi: <b>" + (r.caps.quality.dpi ? (Array.isArray(r.caps.quality.dpi) ? r.caps.quality.dpi.join("/") : r.caps.quality.dpi) : "driver decides") + "</b>");
  }
  if (r.caps.duplex) parts.push("duplex: <b>" + r.caps.duplex.join("/") + "</b>");
  if (r.caps.tray === null) parts.push("tray: <b>no</b>");
  note.innerHTML = "<b>" + p + "</b> supports: " + parts.join(" &middot; ");
}

/* ---------- v2.2: LAN sharing + peers (LAN / PCs tab) ---------- */
async function loadLan() {
  const st = await send({ type: "hubStatus" });
  const dot = $("lanDot"), state = $("lanState"), url = $("lanUrl");
  if (!st.ok) {
    dot.className = "dot offline";
    state.textContent = "Hub offline";
    url.textContent = "start the hub first";
    $("bLanToggle").textContent = "Enable";
    $("peersBody").innerHTML = '<tr><td colspan="4">Hub offline.</td></tr>';
    return;
  }
  const on = !!st.share_lan;
  dot.className = "dot" + (on ? "" : " paused");
  state.textContent = on ? "ON - other PCs can print through this PC" : "OFF - this PC only (127.0.0.1)";
  url.textContent = on ? (st.lan_url || "") : "";
  if (on && st.lan_active === false)
    state.textContent = "SAVED - restart the hub (tray icon > Exit, start again) to apply";
  $("bLanToggle").textContent = on ? "Disable" : "Enable";
  const pr = await send({ type: "hubPeers" });
  const peers = (pr.ok && (pr.peers || pr.parsed)) || [];
  const body = $("peersBody");
  if (!peers.length) {
    body.innerHTML = '<tr><td colspan="4">No peer PCs configured. Add them in the hub config.json under "peer_hubs" - see About > Open user guide. (You can still shift by typing the other PC\'s LAN URL below.)</td></tr>';
    return;
  }
  body.innerHTML = "";
  for (const p of peers) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td class="mono">${p.url || ""}</td>` +
      `<td><span class="st ${p.alive ? "printed" : "failed"}">${p.alive ? "online" : "offline"}</span></td>` +
      `<td>${p.version || ""}</td>`;
    const td = document.createElement("td");
    const b = document.createElement("button");
    b.className = "mini"; b.textContent = "Shift all waiting";
    b.addEventListener("click", async () => {
      if (!confirm("Shift ALL waiting jobs to " + p.url + "?")) return;
      const r = await send({ type: "queueShift", scope: "all", target: p.url });
      alert(r.ok ? r.message || "shifted" : "Shift failed: " + r.error);
      loadLan();
    });
    td.appendChild(b);
    tr.appendChild(td);
    body.appendChild(tr);
  }
}

/* ---------- load / save ---------- */
async function loadPrinters() {
  const r = await send({ type: "hubPrinters" });
  PRINTERS = (r.ok && r.printers) || [];
  const sel = $("defaultPrinter");
  sel.innerHTML = "";
  sel.appendChild(new Option("OS default printer", ""));
  sel.appendChild(new Option("File (save as PDF, no paper)", "__file__"));
  PRINTERS.forEach((p) =>
    sel.appendChild(new Option(
      p.name + (p.is_group ? "  (group)"
              : (p.status && p.status !== "unknown"
                 ? "  [" + p.status + "]" : "") +
              (p.is_default ? "  (OS default)" : ""), p.name))));
  // refresh printer dropdowns in rules
  const cfg = await send({ type: "getCfg" });
  if (cfg.ok) renderRules(cfg.cfg.rules);
}

async function loadAll() {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return;
  const c = cfg.cfg;
  $("hubUrl").value = c.hubUrl || "";
  $("token").value = c.token || "";
  $("enabled").checked = c.enabled !== false;
  $("queueMode").checked = c.queueMode !== false;
  $("retryOffline").checked = c.retryOffline !== false;
  $("langSelect").value = c.lang || "auto";
  $("debugMode").checked = !!c.debugMode;   // v2.3 Debug switch
  $("autoPrintAllPdfs").checked = c.autoPrintAllPdfs !== false;
  $("hookPrint").checked = !!c.hookPrint;
  $("closeAfterPrint").checked = c.closeAfterPrint !== false;
  $("failFallback").value = c.failFallback === "none" ? "none" : "tab";
  $("contextMenu").checked = !!c.contextMenu;
  $("badge").checked = !!c.badge;
  applyPrintDefaults(c.printDefaults);
  await loadPrinters();
  $("defaultPrinter").value = c.defaultPrinter || "";
  refreshCaps();
  testHub(false);
  loadHubCfg();
}

async function saveAll() {
  // v2.6.5: an empty token field keeps the STORED token - the legacy
  // default is never silently re-written by saving with a cleared field.
  const tok = $("token").value.trim();
  const r = await send({
    type: "saveCfg",
    patch: {
      hubUrl: $("hubUrl").value.trim() || "http://127.0.0.1:9235",
      ...(tok ? { token: tok } : {}),
      enabled: $("enabled").checked,
      queueMode: $("queueMode").checked,
      debugMode: $("debugMode").checked,   // v2.3: background also syncs
                                           // the hub config (debug on/off)
      retryOffline: $("retryOffline").checked,
      lang: $("langSelect").value || "auto",
      defaultPrinter: $("defaultPrinter").value,
      autoPrintAllPdfs: $("autoPrintAllPdfs").checked,
      hookPrint: $("hookPrint").checked,
      closeAfterPrint: $("closeAfterPrint").checked,
      failFallback: $("failFallback").value,
      contextMenu: $("contextMenu").checked,
      badge: $("badge").checked,
      printDefaults: PD(),
      rules: collect()
    }
  });
  saved(r.ok ? "Saved" : "Save failed: " + r.error);
}

/* ---------- hub test ---------- */
/* v2.6.5: header status pill - same states as the connection line,
 * visible from every tab so the hub state is never a mystery. */
function setPill(state, text) {
  const pill = $("hubPill"), dot = $("pillDot"), txt = $("pillTxt");
  if (!pill || !dot || !txt) return;          // older markup - ignore
  pill.classList.remove("online", "warn", "offline");
  if (state) pill.classList.add(state);
  txt.textContent = text;
}

async function testHub(verbose = true) {
  const prev = await send({ type: "getCfg" });
  if (prev.ok) {
    // test with what's typed, not what's stored
    await send({ type: "saveCfg", patch: {
      hubUrl: $("hubUrl").value.trim() || prev.cfg.hubUrl,
      token: $("token").value.trim() || prev.cfg.token } });
  }
  const r = await send({ type: "hubStatus" });
  if (r.ok) {
    $("hubState").textContent =
      "CONNECTED - v" + r.version + " - " +
      ((r.printers_count) || "") + (r.default_printer ? " default: " + r.default_printer : "");
    $("hubState").style.color = "#16a34a";
    setPill("online", "hub online");
  } else if (r.reason === "auth" || r.reason === "locked") {
    // v2.6.4: the hub ANSWERED - it is running, the token is the problem.
    $("hubState").textContent =
      "HUB RUNNING - token problem: " + (r.error || r.reason) +
      " - click Detect token";
    $("hubState").style.color = "#d97706";
    setPill("warn", "token problem");
  } else if (r.reason === "slow") {
    // v2.6.4: the hub is listening but /health has not answered yet.
    $("hubState").textContent =
      "HUB STARTING - it is listening but not answering yet, try again in a few seconds";
    $("hubState").style.color = "#d97706";
    setPill("warn", "starting…");
  } else {
    $("hubState").textContent = "OFFLINE - start the hub first";
    $("hubState").style.color = "#dc2626";
    setPill("offline", "hub offline");
  }
  if (r.ok) await loadPrinters();
  if (verbose) await loadAll();
}

/* ---------- jobs (v2.7.0 history manager) ----------
 * HIST_JOBS = last hub payload; HIST_SEL = ticked ids (survives the
 * 8 s auto-refresh). Filter + search happen client-side, so switching
 * views never re-hits the hub. */
let HIST_JOBS = [];
const HIST_SEL = new Set();
function histFilteredJobs() {
  const f = ($("histFilter") || {}).value || "";
  const s = (($("histSearch") || {}).value || "").trim().toLowerCase();
  let rows = HIST_JOBS;
  if (f === "not_printed")
    rows = rows.filter((j) => ["failed", "dead", "canceled"].includes(j.status));
  else if (f) rows = rows.filter((j) => j.status === f);
  if (s)
    rows = rows.filter((j) => (j.title || "").toLowerCase().includes(s) ||
      (j.printer || "").toLowerCase().includes(s) ||
      String(j.id) === s.replace("#", ""));
  return rows;
}
async function loadJobs() {
  const limitEl = $("histLimit");
  const limit = limitEl ? Number(limitEl.value || 100) : 100;
  const r = await send({ type: "hubJobs", limit });
  HIST_JOBS = (r.ok && r.jobs) || [];
  renderJobs();
}
function renderJobs() {
  const body = $("jobsBody");
  body.innerHTML = "";
  const rows = histFilteredJobs();
  if (!HIST_JOBS.length) {
    body.innerHTML = '<tr><td colspan="8">Hub offline - start it with: python advprint.py serve</td></tr>';
    return;
  }
  for (const j of rows) {
    const tr = document.createElement("tr");
    const why = j.held_reason || j.error || "";
    tr.innerHTML =
      `<td><input type="checkbox" ${HIST_SEL.has(j.id) ? "checked" : ""} title="tick to reprint" onchange="histSel(${j.id},this.checked)"></td>` +
      `<td>${j.id}</td><td class="mono">${(j.created_at || "").replace("T", " ")}</td>` +
      `<td>${(j.title || "-").slice(0, 42)}</td><td>${(j.printer || "default").slice(0, 28)}</td>` +
      `<td>${j.kind || "-"}</td><td><span class="st ${j.status}" title="${String(why).replace(/"/g, "&quot;")}">${j.status}</span>` +
      (why ? `<div class="jerr">${String(why).replace(/</g, "&lt;").slice(0, 90)}</div>` : "") + `</td>`;
    const tdBtn = document.createElement("td");
    if (j.status === "queued" || j.status === "printing" || j.status === "scheduled"
        || j.status === "held") {
      const bc = document.createElement("button");
      bc.className = "mini danger"; bc.textContent = "Cancel";
      bc.addEventListener("click", async () => {
        await send({ type: "jobAction", id: j.id, action: "cancel" });
        loadJobs();
      });
      tdBtn.appendChild(bc);
      // v2.2.1: Print now - bypasses the pause and the printer-status
      // hold (the remedy when jobs sit in the queue and never print)
      if (j.status !== "printing") {
        const bp = document.createElement("button");
        bp.className = "mini"; bp.textContent = "Print now";
        bp.title = "Send this job to the printer immediately " +
                   "(bypasses pause and printer-status hold)";
        bp.addEventListener("click", async () => {
          bp.disabled = true; bp.textContent = "...";
          const pr = await send({ type: "jobPrintNow", id: j.id });
          if (!pr.ok) alert("Print now failed: " + (pr.error || "no response"));
          loadJobs();
        });
        tdBtn.appendChild(bp);
      }
    } else if (j.status === "failed" || j.status === "dead" || j.status === "canceled") {
      const br = document.createElement("button");
      br.className = "mini"; br.textContent = "Retry";
      br.title = "Queue this job again - choose another printer if you like";
      br.addEventListener("click", async () => {
        const p = prompt("Retry on which printer? (empty = the same printer)",
                         j.printer || "");
        if (p === null) return;                       // user canceled
        await send({ type: "jobRetry", id: j.id, printer: p.trim() });
        loadJobs();
      });
      tdBtn.appendChild(br);
    } else {
      const br = document.createElement("button");
      br.className = "mini"; br.textContent = "Reprint";
      br.addEventListener("click", async () => {
        const reason = prompt("Reprint - reason? (saved to the audit log)");
        if (reason === null) return;
        await send({ type: "jobReprint", id: j.id, reason: reason });
        loadJobs();
      });
      tdBtn.appendChild(br);
    }
    tr.appendChild(tdBtn);
    body.appendChild(tr);
  }
  if (!rows.length) {
    const f = ($("histFilter") || {}).value || "";
    const s = (($("histSearch") || {}).value || "").trim();
    body.innerHTML = '<tr><td colspan="8">No jobs' +
      ((f || s) ? " match this filter." : " yet.") + '</td></tr>';
  }
  // master checkbox + selected counter
  const all = $("histAll");
  const sel = rows.filter((j) => HIST_SEL.has(j.id)).length;
  all.checked = rows.length > 0 && sel === rows.length;
  all.indeterminate = sel > 0 && sel < rows.length;
  $("histSelCnt").textContent = HIST_SEL.size + " selected";
}
function histSel(id, on) {
  on ? HIST_SEL.add(id) : HIST_SEL.delete(id);
  const all = $("histAll");
  const rows = histFilteredJobs();
  const sel = rows.filter((j) => HIST_SEL.has(j.id)).length;
  all.checked = rows.length > 0 && sel === rows.length;
  all.indeterminate = sel > 0 && sel < rows.length;
  $("histSelCnt").textContent = HIST_SEL.size + " selected";
}
$("histFilter").addEventListener("change", renderJobs);
$("histSearch").addEventListener("input", renderJobs);
$("histLimit").addEventListener("change", loadJobs);
$("histAll").addEventListener("change", (e) => {
  for (const j of histFilteredJobs())
    e.target.checked ? HIST_SEL.add(j.id) : HIST_SEL.delete(j.id);
  renderJobs();
});
$("bHistReprintSel").addEventListener("click", async () => {
  if (!HIST_SEL.size) return saved("Tick one or more rows in the history first");
  if (!confirm("Reprint " + HIST_SEL.size + " selected job(s)?")) return;
  const r = await send({ type: "jobBulkReprint", ids: [...HIST_SEL] });
  saved(r.ok
    ? "Reprint queued: " + r.queued + " job(s)" +
      (r.skipped ? " - " + r.skipped + " skipped (original file gone)" : "")
    : "Failed: " + (r.error || "no response"));
  HIST_SEL.clear();
  loadJobs();
});
$("bHistReprintNot").addEventListener("click", async () => {
  if (!confirm("Reprint EVERY failed / dead / canceled job in the loaded history?\n" +
               "Jobs whose original file is gone are skipped.")) return;
  const r = await send({ type: "jobBulkReprint", scope: "not_printed" });
  saved(r.ok
    ? "Reprint queued: " + r.queued + " job(s)" +
      (r.skipped ? " - " + r.skipped + " skipped (original file gone)" : "")
    : "Failed: " + (r.error || "no response"));
  HIST_SEL.clear();
  loadJobs();
});
$("bHistClearHub").addEventListener("click", async () => {
  if (!confirm("Delete ALL finished jobs (printed / failed / dead / canceled / forwarded / saved) from the HUB history?\n\n" +
               "Waiting jobs (queued / printing / held / scheduled) are NEVER touched.\n" +
               "This cannot be undone - export the CSV first if unsure.")) return;
  const r = await send({ type: "historyClear" });
  saved(r.ok ? (r.message || ("History cleared - " + r.deleted + " job(s) removed"))
             : "Failed: " + (r.error || "no response"));
  HIST_SEL.clear();
  loadJobs();
});

/* ---------- v2.6: one-click token detection (loopback fix) ---------- */
$("bDetectToken").addEventListener("click", async () => {
  const note = $("hubState");
  note.style.color = "#64748b";
  note.textContent = "detecting...";
  const r = await send({ type: "tokenDetect",
                         hubUrl: $("hubUrl").value.trim() });
  if (r.ok) {
    $("token").value = r.token;
    note.style.color = "#16a34a";
    note.textContent = "token detected (hub v" + (r.version || "?") + ")";
    saved("Token detected and saved");
    testHub(false);
  } else {
    note.style.color = "#dc2626";
    note.textContent = r.error || "not detected";
  }
});

/* ---------- v2.6: hub-side settings (GET/POST /config) ---------- */
const HUB_FIELDS = [
  ["hMaxRetries", "max_retries", "int"],
  ["hRetryBase", "retry_base_seconds", "int"],
  ["hDedupe", "dedupe_minutes", "int"],
  ["hHoldOffline", "hold_offline", "bool"],
  ["hInstantQueue", "instant_auto_queue", "bool"],
  ["hAuthFails", "max_auth_failures", "int"],
  ["hLockMin", "lockout_minutes", "int"],
  ["hLoopbackExempt", "lockout_exempt_loopback", "bool"],
  ["hHeaderOnly", "token_header_only", "bool"],
  ["hWatermark", "reprint_watermark", "bool"],
  ["hReasonRequired", "reprint_reason_required", "bool"],
  ["hAudit", "audit_enabled", "bool"],
  ["hSumatra", "sumatra_path", "str"],
  ["hFileDir", "file_dir", "str"],
];

function hubCfgToUi(c) {
  for (const [id, key] of HUB_FIELDS) {
    const el = $(id);
    if (!el) continue;
    const v = c[key];
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = (v == null ? "" : String(v));
  }
  $("hThermalEngine").value = c.thermal_text_engine || "auto";
  $("hCodepage").value = c.escpos_codepage || "cp437";
  const origins = Array.isArray(c.allowed_origins) ? c.allowed_origins : [];
  $("hOrigins").value = origins.join(", ");
}

function uiToHubCfg() {
  const patch = {};
  for (const [id, key, kind] of HUB_FIELDS) {
    const el = $(id);
    if (!el) continue;
    if (kind === "bool") patch[key] = el.checked;
    else if (kind === "int") {
      const v = parseInt(el.value, 10);
      if (!isNaN(v)) patch[key] = v;
    } else patch[key] = el.value.trim();
  }
  patch.thermal_text_engine = $("hThermalEngine").value;
  patch.escpos_codepage = $("hCodepage").value;
  patch.allowed_origins = $("hOrigins").value.split(",")
    .map((x) => x.trim()).filter(Boolean);
  return patch;
}

async function loadHubCfg() {
  const r = await send({ type: "hubConfigGet" });
  const msg = $("hubCfgMsg");
  if (!r.ok) {
    msg.textContent = "hub offline - start it, then Reload";
    return;
  }
  hubCfgToUi(r.cfg || r.parsed || r);
  msg.textContent = "";
}

$("bHubCfgReload").addEventListener("click", loadHubCfg);
$("bHubCfgSave").addEventListener("click", async () => {
  const r = await send({ type: "hubConfigSet", patch: uiToHubCfg() });
  const msg = $("hubCfgMsg");
  if (r.ok) {
    const ch = (r.changed && r.changed.length) ? " (" + r.changed.join(", ") + ")" : "";
    msg.textContent = "applied" + ch;
    if ((r.changed || []).includes("share_lan")) saved("restart the hub to apply LAN change");
  } else msg.textContent = "failed: " + (r.error || "no response");
  setTimeout(() => { $("hubCfgMsg").textContent = ""; }, 6000);
});

/* ---------- v2.6: Debug tab full self-test ---------- */
$("bDbgLivetest").addEventListener("click", async () => {
  const box = $("dbgLivetest");
  box.style.display = "block";
  box.textContent = "running full self-test...";
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) { box.textContent = "extension config error"; return; }
  const base = (cfg.cfg.hubUrl || "http://127.0.0.1:9235").replace(/\/+$/, "");
  try {
    const res = await fetch(base + "/livetest", {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 "X-AdvPrint-Token": cfg.cfg.token || "" },
      body: "{}" });
    const d = await res.json();
    if (!d.ok) { box.textContent = "self-test failed: " + (d.error || res.status); return; }
    const lines = (d.steps || []).map((st) =>
      "[" + (st.pass ? "OK" : "!!") + "] " + st.name + (st.info ? "  - " + st.info : ""));
    lines.push("");
    lines.push(d.all_ok
      ? "ALL CHECKS PASSED - AdvPrint Pro is production-ready on this PC."
      : "FIX THE [!!] ITEMS ABOVE, then run the self-test again.");
    box.textContent = lines.join("\n");
  } catch (e) {
    box.textContent = "self-test error: " + e.message + " (hub offline?)";
  }
});

/* ---------- wire up ---------- */
$("bTestHub").addEventListener("click", () => testHub(true));
$("bReloadPrinters").addEventListener("click", loadPrinters);
$("bAddRule").addEventListener("click", () => {
  $("rulesBody").appendChild(ruleRow({ pattern: "", printer: "", action: "auto", auto: false }));
});
$("bSave").addEventListener("click", saveAll);
$("bTestPage").addEventListener("click", async () => {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return;
  const base = cfg.cfg.hubUrl.replace(/\/+$/, "");
  const res = await fetch(base + "/testprint?kind=a4", {
    headers: { "X-AdvPrint-Token": cfg.cfg.token }
  }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
  saved(res.ok ? "Test page queued" : "Failed: " + (res.error || "offline"));
  loadJobs();
});
$("bPrintPdf").addEventListener("click", async () => {
  const url = $("pdfUrl").value.trim();
  if (!url) return saved("Enter a PDF URL first");
  const r = await send({ type: "printPdfUrl", url, title: "manual-print" });
  saved(r.ok ? "Queued as job #" + r.job_id : "Failed: " + r.error);
  loadJobs();
});
$("bReloadJobs").addEventListener("click", loadJobs);
$("bClearHist").addEventListener("click", async () => {
  await chrome.storage.local.set({ history: [] });
  saved("Extension history copy cleared (hub history untouched - use 'Clear ALL hub history' for that)");
});
["enabled", "queueMode", "debugMode", "retryOffline", "autoPrintAllPdfs", "hookPrint",
 "closeAfterPrint", "failFallback", "contextMenu", "badge", "defaultPrinter"].forEach((id) =>
  $(id).addEventListener("change", saveAll));

$("langSelect").addEventListener("change", async () => {
  await saveAll();
  const lang = await AdvPrintI18n.currentLang();
  AdvPrintI18n.apply(lang);
});

/* v2.0: hub dashboard + audit log (token comes from the saved config) */
async function openHubPath(path) {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return;
  const base = (cfg.cfg.hubUrl || "http://127.0.0.1:9235").replace(/\/+$/, "");
  chrome.tabs.create({ url: base + path + "?token=" +
                       encodeURIComponent(cfg.cfg.token || "") });
}
$("bDashboard").addEventListener("click", () => openHubPath("/dashboard"));
$("bAudit").addEventListener("click", () => openHubPath("/audit"));
$("bOpenDocs").addEventListener("click", () => openHubPath("/docs"));

/* ---------- v2.2: LAN / PCs wiring ---------- */
$("bLanToggle").addEventListener("click", async () => {
  const st = await send({ type: "hubStatus" });
  if (!st.ok) return alert("Hub offline - start it first");
  const on = !st.share_lan;
  if (!confirm(on ?
      "Enable LAN sharing?\n\nAfter this, RESTART the hub (tray icon > Exit, start again) and allow TCP 9235 through the firewall. Other PCs will need your token." :
      "Disable LAN sharing? Other PCs will no longer reach this printer.")) return;
  const r = await send({ type: "hubConfigSet", patch: { share_lan: on } });
  if (r.ok) alert(on ?
      "Saved. NOW: 1) restart the hub (tray icon > Exit, start AdvPrint Pro again)  2) allow TCP 9235 through the firewall.\nThis PC's LAN URL will be shown after the restart." :
      "Saved. Restart the hub to fully apply.");
  else alert("Failed: " + r.error);
  loadLan();
});
$("bLanCopy").addEventListener("click", async () => {
  const u = $("lanUrl").textContent.trim();
  if (!u) return;
  try { await navigator.clipboard.writeText(u); alert("Copied: " + u); }
  catch (_) { prompt("Copy this LAN URL:", u); }
});
$("bLanRefresh").addEventListener("click", loadLan);
$("bShiftAll").addEventListener("click", async () => {
  const target = $("shiftTarget").value.trim();
  if (!target) return alert("Enter the other PC's LAN URL first\n(e.g. http://192.168.0.60:9235)");
  if (!confirm("Shift ALL waiting jobs to " + target + "?")) return;
  const r = await send({ type: "queueShift", scope: "all", target,
                         targetToken: $("shiftToken").value.trim() });
  alert(r.ok ? r.message || "shifted" : "Shift failed: " + r.error);
  loadLan();
});

/* ---------- v2.3: Debug tab (WHEN / WHY / WHERE is the problem) ---------- */
function dbgEsc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function stopDebugLoop() {
  if (DEBUG_TIMER) { clearInterval(DEBUG_TIMER); DEBUG_TIMER = null; }
}
function startDebugLoop() {
  stopDebugLoop();
  loadDebug();
  DEBUG_TIMER = setInterval(loadDebug, 6000);
}

async function loadDebug() {
  const d = await send({ type: "hubDebug" });
  const st = $("dbgState");
  const note = $("dbgNote");
  const problems = $("dbgProblems");
  const reports = $("dbgReports");
  const badge = $("tabDbgBadge");
  if (!d.ok) {
    $("dbgDot").className = "dot offline";
    st.textContent = "Hub offline or /debug unavailable - start the hub, then the report appears here";
    note.textContent = "";
    problems.innerHTML = '<tr><td colspan="4">No hub connection.</td></tr>';
    reports.innerHTML = '<tr><td colspan="4">No hub connection.</td></tr>';
    badge.classList.remove("show");
    return;
  }
  $("dbgDot").className = "dot" + (d.worker_alive && !d.paused ? "" : " paused");
  st.textContent =
    "hub v" + d.version + " - Debug mode " + (d.debug ? "ON" : "OFF") +
    " - worker " + (d.worker_alive ? "running" : "NOT RUNNING") +
    " - queue " + (d.paused ? "PAUSED" : "running") +
    " - printers ready: " + (d.printers || [])
      .filter((p) => p.status === "ready").length + "/" + (d.printers || []).length +
    " - instant auto-queue " + (d.instant_auto_queue ? "on" : "off");
  note.textContent = d.debug
    ? "Debug mode is ON - print once more, then read the problems below. The Copy report button gives you everything for a bug report."
    : "Debug mode is OFF - turn it ON in Settings > Debug mode (or the dashboard Debug card) so browser errors are collected too.";
  let nerr = 0;
  problems.innerHTML = (d.problems || []).map((p) => {
    if (p.level === "error") nerr++;
    const cls = p.level === "error" ? "st failed"
              : p.level === "warn" ? "st held" : "st queued";
    return "<tr><td><span class='" + cls + "'>" + dbgEsc(p.level) +
           "</span></td><td>" + dbgEsc(p.check) + "</td><td>" +
           dbgEsc(p.message) + "</td><td>" + dbgEsc(p.fix || "-") +
           "</td></tr>";
  }).join("") || '<tr><td colspan="4">No problems listed.</td></tr>';
  reports.innerHTML = (d.client_reports || []).length
    ? d.client_reports.slice().reverse().map((r) =>
        "<tr><td>" + dbgEsc(String(r.ts || "").replace("T", " ")) +
        "</td><td>" + dbgEsc(r.source || "?") +
        "</td><td><span class='" +
        (r.level === "error" ? "st failed" : r.level === "warn" ? "st held" : "st queued") +
        "'>" + dbgEsc(r.level || "?") + "</span></td><td>" +
        dbgEsc(r.message || "") +
        (r.context ? " <small class='mono'>" + dbgEsc(r.context).slice(0, 160) +
        "</small>" : "") + "</td></tr>").join("")
    : '<tr><td colspan="4">No client error reports yet' +
      (d.debug ? " - print once more with Debug mode ON." :
                 " (Debug mode is OFF in Settings).") + "</td></tr>";
  badge.textContent = String(nerr);
  badge.classList.toggle("show", nerr > 0);
}

$("bDbgRefresh").addEventListener("click", loadDebug);
$("bDbgTest").addEventListener("click", async () => {
  await send({ type: "debugTestReport" });
  setTimeout(loadDebug, 600);
});
$("bDbgCopy").addEventListener("click", async () => {
  const d = await send({ type: "hubDebug" });
  if (!d.ok) return saved("Nothing to copy - hub offline");
  try {
    await navigator.clipboard.writeText(JSON.stringify(d, null, 2));
    saved("Full /debug report copied - paste it into your bug report");
  } catch (_) { saved("Copy blocked by the browser - use Open /debug JSON"); }
});
$("bDbgJson").addEventListener("click", () => openHubPath("/debug"));


/* default print options: save on change + capability hints */
["dCopies", "dPagesMode", "dPagesCustom", "dQuality", "dQualityCustom",
 "dPerSheet", "dDuplex", "dOrient", "dScale", "dMargin", "dPaper"]
 .forEach((id) => $(id).addEventListener("change", saveAll));
$("dPagesMode").addEventListener("change", () => {
  $("dPagesCustom").style.display = $("dPagesMode").value === "custom" ? "" : "none";
});
$("dQuality").addEventListener("change", () => {
  $("dQualityCustom").style.display = $("dQuality").value === "custom" ? "" : "none";
});
$("defaultPrinter").addEventListener("change", refreshCaps);

/* ---------- tab bar + queue/about wiring ---------- */
document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));
$("bQPause").addEventListener("click", async () => {
  const st = await send({ type: "hubStatus" });
  await send({ type: "queueAction", action: st.ok && st.paused ? "resume" : "pause" });
  refreshQueue();
});
$("bQClear").addEventListener("click", async () => {
  await send({ type: "queueAction", action: "clear" });
  refreshQueue();
});
$("bQRefresh").addEventListener("click", refreshQueue);
$("bUpdateCheck").addEventListener("click", updateCheck);

loadAll();
pickDefaultTab();
AdvPrintI18n.currentLang().then((lang) => AdvPrintI18n.apply(lang));
/* v2.7.0: the About panel shows the REAL manifest version - it used to
 * stay on whatever was hardcoded in the HTML (stuck at 2.6.4). */
try {
  $("aboutVer").textContent = chrome.runtime.getManifest().version;
} catch (_) { /* keep the HTML default */ }
