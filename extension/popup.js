/* AdvPrint Pro - popup logic */
const $ = (id) => document.getElementById(id);
let paused = false;

function msg(text, cls) {
  const el = $("msg");
  el.textContent = text || "";
  el.className = cls || "";
}

function send(m) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(m, (r) => resolve(r || { ok: false, error: "no response" }));
  });
}

/* ---------- v2.0: offline banner + retry queue ---------- */
function showOffline(on, count) {
  const b = $("offlineBanner");
  b.classList.toggle("show", !!on);
  if (on) {
    const n = count || 0;
    $("offlineText").textContent = AdvPrintI18n.t("popOffline") +
      (n ? " - " + n + " " + AdvPrintI18n.t("popRetryCount") : "");
  }
}

function showTokenWarning(on, mode) {
  $("tokenBanner").classList.toggle("show", !!on);
  if (on) {
    // v2.1.0: mode "token"=401, "locked"=429, "default"=legacy token
    $("tokenText").textContent = mode === "token"
      ? AdvPrintI18n.t("popTokenBad")
      : mode === "locked"
        ? AdvPrintI18n.t("popTokenLocked")
        : AdvPrintI18n.t("popTokenWarn");
  }
}

$("bRetry").addEventListener("click", async () => {
  msg("Retrying parked jobs...", "info");
  const r = await send({ type: "flushRetries" });
  if (r.ok) msg((r.sent || 0) + " job(s) delivered to the hub", "info");
  showOffline(false);
  refresh();
});

$("bTokenHelp").addEventListener("click", () => {
  // v3.0.6: the Settings tab was split - the token fields live in the
  // CONNECTIONS tab now (old #settings hash still lands in General)
  chrome.tabs.create({ url: "options.html#connections" });
});

/* v2.6.2: ONE-CLICK token fix straight from the popup. The hub keeps
 * refusing our stored token (401) - ask it for the current token via
 * /token/current (loopback only) and retry. No Options visit needed. */
$("bFixToken").addEventListener("click", async () => {
  const b = $("bFixToken");
  b.disabled = true;
  msg(AdvPrintI18n.t("popFixTokenWorking"), "info");
  const r = await send({ type: "tokenDetect" });
  b.disabled = false;
  if (r && r.ok) {
    msg(AdvPrintI18n.t("popFixTokenOk"), "info");
    await chrome.storage.local.remove("authProblem");
    refresh();
  } else {
    msg(AdvPrintI18n.t("popFixTokenFail") +
        "  [" + ((r && r.error) || "?") + "]", "err");
  }
});

/* ---------- master switches (Enable / Queue Mode / LAN sharing) ---- */
function renderEnabledState(off) {
  document.body.classList.toggle("off", off);
  $("swEnabledRow").classList.toggle("off", off);
  $("swEnabledSub").textContent = off ? AdvPrintI18n.t("popEnabledOff")
                                      : AdvPrintI18n.t("popEnabledOn");
  ["bPage", "bFile", "bShot", "bTest"].forEach((id) => { $(id).disabled = off; });
  $("bPause").disabled = off;
}

async function loadSwitches() {
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return;
  const off = cfg.cfg.enabled === false;
  $("swEnabled").checked = !off;
  $("swQueue").checked = cfg.cfg.queueMode !== false;
  // v3.0.6: the auto-print rules switch was REMOVED from the popup - it
  // lives in Options only now (Rules tab power switch + General > Power
  // switches, one shared setting). Manual prints from this popup
  // keep working either way; pausing only stops the HIDDEN auto work.
  // v3.0.2: the window.print() hook switch lives ONLY in Options >
  // Power switches now (setting key: hookPrint) - the popup row was
  // removed to keep the popup lean; the hookPrint setting itself and
  // its behaviour are unchanged.
  // v2.8: Share SEND Mode = the print ROUTE (LAN PC vs this PC).
  // Share RECEIVE state comes from the hub in refresh() (self share_lan).
  $("swShareTx").checked = cfg.cfg.lanSend === true;
  await renderShareTxState(cfg.cfg.lanSend === true, cfg.cfg);
  renderEnabledState(off);
}

async function renderShareTxState(on, cfg) {
  let sub;
  if (!on) {
    sub = AdvPrintI18n.t("popShareTxOff");
  } else {
    const c = cfg || (await send({ type: "getCfg" })).cfg || {};
    sub = c.hubUrlLan
      ? (AdvPrintI18n.t("popShareTxOnLan") + " " + c.hubUrlLan)
      : AdvPrintI18n.t("popShareTxNoUrl");
  }
  $("swShareTxSub").textContent = sub;
  $("swShareTxRow").classList.toggle("off", !on);
}

function renderShareRxState(on, reachable) {
  const sw = $("swShareRx");
  sw.checked = !!on;
  sw.disabled = !reachable;
  $("swShareRxSub").textContent = !reachable
    ? AdvPrintI18n.t("popShareRxOffline")
    : (on ? AdvPrintI18n.t("popShareRxOn") : AdvPrintI18n.t("popShareRxOff"));
  $("swShareRxRow").classList.toggle("off", reachable ? !on : true);
}

$("swEnabled").addEventListener("change", async () => {
  const on = $("swEnabled").checked;
  await send({ type: "saveCfg", patch: { enabled: on } });
  renderEnabledState(!on);
  msg(on ? "AdvPrint enabled" : "AdvPrint disabled - nothing will print", "info");
});

$("swQueue").addEventListener("change", async () => {
  const on = $("swQueue").checked;
  await send({ type: "saveCfg", patch: { queueMode: on } });
  $("swQueueSub").textContent = on
    ? AdvPrintI18n.t("popQueueOn")
    : AdvPrintI18n.t("popQueueOff");
  msg(on ? AdvPrintI18n.t("popQueueOnMsg")
         : AdvPrintI18n.t("popQueueOffMsg"), "info");
});

/* v3.0.6: the popup rules switch was removed - the power switch for all
 * auto-print rules lives in Options (Rules tab + General > Power
 * switches). Pausing stops only the HIDDEN auto work; every manual
 * print (this popup's buttons, right-click menu) keeps working. */

/* v2.7.0: Share Receive Mode - hub-side share_lan (accept jobs from
 * other PCs on the LAN). Saved straight into the hub config; a hub
 * restart applies the new listener binding. */
$("swShareRx").addEventListener("change", async () => {
  const on = $("swShareRx").checked;
  const r = await send({ type: "hubConfigSet", patch: { share_lan: on } });
  if (r && r.ok) {
    renderShareRxState(on, true);
    msg(AdvPrintI18n.t(on ? "popShareRxMsgOn" : "popShareRxMsgOff"), "info");
  } else {
    $("swShareRx").checked = !on;
    msg("Failed: " + ((r && r.error) || "hub offline") +
        "  (start AdvPrint Pro first)", "err");
  }
});

/* v3.0.2: the popup window.print() hook toggle was removed - the switch
 * lives in Options > Power switches > Intercept window.print(). */

/* v2.8: Share Send Mode = the print ROUTE. ON sends every print job to
 * the LAN PC hub (Options > LAN PC profile), OFF prints on this PC.
 * When no LAN PC is configured, Options opens at the LAN section. */
$("swShareTx").addEventListener("change", async () => {
  const on = $("swShareTx").checked;
  if (on) {
    const cfg = await send({ type: "getCfg" });
    if (!cfg.ok || !cfg.cfg.hubUrlLan) {
      $("swShareTx").checked = false;
      msg(AdvPrintI18n.t("popShareTxNoUrl"), "err");
      chrome.tabs.create({ url: "options.html#lan-settings" });
      return;
    }
  }
  await send({ type: "saveCfg", patch: { lanSend: on } });
  await renderShareTxState(on);
  msg(on ? AdvPrintI18n.t("popShareTxMsgOn")
         : AdvPrintI18n.t("popShareTxMsgOff"), "info");
  refresh();
});

async function refresh() {
  const st = await send({ type: "hubStatus" });
  if (st.ok) {
    // v2.8: the status line names the ACTIVE print target
    $("dot").classList.add("on");
    $("stat").textContent = st.lan_used
      ? `Printing on LAN PC - hub v${st.version}`
      : `Connected - hub v${st.version} on ${st.os}`;
    $("connect").textContent = "";
    paused = !!st.paused;
    const qs = $("qstate");
    qs.textContent = paused ? AdvPrintI18n.t("popPaused")
                            : AdvPrintI18n.t("popRunning");
    // v2.2.1: PAUSED must be unmissable - red text (a paused queue is
    // the #1 reason jobs "stay queued" and nothing prints)
    qs.classList.toggle("paused", paused);
    $("bPause").textContent = paused ? AdvPrintI18n.t("popResume")
                                     : AdvPrintI18n.t("popPause");
    $("qpend").textContent = st.pending ? st.pending + " pending" : "";
    // v2.8: Share RECEIVE state lives on the SELF hub (/health share_lan)
    renderShareRxState(!!st.self_share_lan, st.self_ok !== false);
    showOffline(false);
    // v2.1.0: token rejected earlier (KEY state) -> red banner; once an
    // authed call succeeds below, the flag is cleared again
    const ap = await chrome.storage.local.get({ authProblem: null });
    if (ap.authProblem) {
      showTokenWarning(true, ap.authProblem.why);
    } else if (st.lan_used && st.lan_reason === "auth") {
      showTokenWarning(true, "token");   // LAN PC rejected its token
    } else {
      showTokenWarning(!!st.default_token_warning, "default");
    }
    // v2.0: hub is back - deliver anything parked while it was down
    const ri = await send({ type: "retryInfo" });
    if (ri.ok && ri.count) {
      const fl = await send({ type: "flushRetries" });
      if (fl.ok && fl.sent) msg(fl.sent + " parked job(s) delivered", "info");
    }
  } else if (st.reason === "auth") {
    /* v2.6.2: the hub ANSWERED but rejected the stored token - it is
     * RUNNING (the desktop tool shows the same hub as running). Never
     * say "offline" here; show the token banner with the one-click
     * fix instead. Background auto-heal has already tried once; this
     * state only appears when that could not succeed (LAN hub etc.). */
    $("dot").classList.remove("on");
    $("stat").textContent = AdvPrintI18n.t("popStatAuth");
    $("connect").textContent = "";
    $("qstate").textContent = "-";
    $("qpend").textContent = "";
    renderShareRxState(false, false);
    showOffline(false);
    showTokenWarning(true, "token");
  } else if (st.reason === "slow") {
    /* v2.6.4: the hub IS listening (TCP accepted) but /health did not
     * answer within 8 s - it is still starting. Never say "offline":
     * the desktop tool already shows it running. */
    $("dot").classList.remove("on");
    $("stat").textContent = AdvPrintI18n.t("popStatSlow");
    $("connect").textContent = "";
    $("qstate").textContent = "-";
    $("qpend").textContent = "";
    renderShareRxState(false, false);
    showOffline(false);
    msg(AdvPrintI18n.t("popStatSlowHint"), "info");
  } else {
    $("dot").classList.remove("on");
    $("stat").textContent = "Hub offline";
    $("connect").textContent = "Connect";
    $("qstate").textContent = "-";
    $("qpend").textContent = "";
    renderShareRxState(false, false);
    const ri = await send({ type: "retryInfo" });
    showOffline(true, ri.ok ? ri.count : 0);
    msg(AdvPrintI18n.t("popHubOfflineHint"), "err");
  }

  const jobs = await send({ type: "hubJobs", limit: 8, target: "print" });
  const box = $("jobs");
  box.innerHTML = "";
  if (jobs.ok) {
    // v2.1.0: an authed call just succeeded -> the token works again;
    // clear the KEY flag so the red banner disappears on next paint
    const ap = await chrome.storage.local.get({ authProblem: null });
    if (ap.authProblem) {
      await chrome.storage.local.remove("authProblem");
      showTokenWarning(!!st.default_token_warning, "default");
    }
  }
  if (jobs.ok && jobs.jobs && jobs.jobs.length) {
    // v2.2.1: held jobs get their own banner with a one-click fix
    let held = [];
    for (const j of jobs.jobs) {
      if (j.status === "held") held.push(j);
      const d = document.createElement("div");
      d.className = "job";
      const why = j.held_reason || j.error || "";
      if (why) d.title = why;
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = j.title || ("job #" + j.id);
      t.title = j.title || "";
      const s = document.createElement("span");
      s.className = "st " + j.status;
      s.textContent = j.status;
      const m = document.createElement("span");
      m.className = "m";
      m.textContent = (j.printer || "default");
      d.append(t, s, m);
      // v2.2.1: one-click "Print now" for anything that is not moving -
      // bypasses the global pause AND the printer-status hold
      if (["queued", "held", "failed", "dead", "scheduled", "saved"]
          .includes(j.status)) {
        const b = document.createElement("button");
        b.className = "pbtn";
        b.textContent = "Print now";
        b.title = "Send this job to the printer immediately " +
                  "(bypasses pause and printer-status hold)";
        b.addEventListener("click", async () => {
          b.disabled = true; b.textContent = "...";
          const r = await send({ type: "jobPrintNow", id: j.id });
          msg(r.ok ? "Job #" + j.id + " - printing now"
                   : "Failed: " + (r.error || "no response"),
             r.ok ? "info" : "err");
          setTimeout(refresh, 1500);
        });
        d.appendChild(b);
      }
      if (why) {
        const e = document.createElement("span");
        e.className = "e";
        e.textContent = why.slice(0, 120);
        d.appendChild(e);
      }
      box.appendChild(d);
    }
    if (held.length) {
      $("heldText").textContent = held.length +
        " job(s) held - the printer reports offline/out of paper.";
      $("heldBanner").classList.add("show");
    } else {
      $("heldBanner").classList.remove("show");
    }
  } else {
    box.innerHTML = '<div class="empty">' + AdvPrintI18n.t("popNoJobs") + '</div>';
    $("heldBanner").classList.remove("show");
  }
}

$("bPage").addEventListener("click", async () => {
  msg("Sending page to printer...", "info");
  const r = await send({ type: "printTab" });
  if (r.ok) { msg("Queued as job #" + r.job_id + " - check the printer", "info"); refresh(); }
  else msg("Failed: " + r.error, "err");
});

$("bFile").addEventListener("click", async () => {
  msg("Saving page as PDF file...", "info");
  const r = await send({ type: "printTab", dest: "file" });
  if (r.ok) {
    msg("Saved: " + (r.file || ("job #" + r.job_id)) +
        "  (open it from the hub history)", "info");
    refresh();
  } else msg("Failed: " + r.error, "err");
});

$("bShot").addEventListener("click", async () => {
  msg("Capturing screenshot...", "info");
  const r = await send({ type: "printScreenshot" });
  if (r.ok) { msg("Screenshot queued as job #" + r.job_id, "info"); refresh(); }
  else msg("Failed: " + r.error, "err");
});

$("bTest").addEventListener("click", async () => {
  // v2.8: the test page prints on the ACTIVE target (LAN PC when
  // Share Send is on), exactly like a normal print job would.
  const cfg = await send({ type: "getCfg" });
  if (!cfg.ok) return msg("Config error", "err");
  const c = cfg.cfg;
  const lan = c.lanSend === true && c.hubUrlLan;
  const base = (lan ? c.hubUrlLan : c.hubUrl).replace(/\/+$/, "");
  const res = await fetch(base + "/testprint?kind=a4", {
    headers: { "X-AdvPrint-Token": lan ? (c.hubTokenLan || c.token) : c.token }
  }).then((r) => r.json()).catch((e) => ({ ok: false, error: String(e) }));
  if (res.ok) { msg("Test page queued as job #" + res.job_id, "info"); refresh(); }
  else msg("Failed: " + (res.error || "hub offline"), "err");
});

$("bPause").addEventListener("click", async () => {
  const r = await send({ type: "queueAction", action: paused ? "resume" : "pause",
                         target: "print" });
  if (r.ok) refresh(); else msg("Failed: " + r.error, "err");
});

/* v2.2.1: print every HELD job right now (printer-status hold bypass) */
$("bPrintHeld").addEventListener("click", async () => {
  msg("Sending held jobs to the printer...", "info");
  const jobs = await send({ type: "hubJobs", limit: 50 });
  if (!jobs.ok) return msg("Failed: " + (jobs.error || "hub offline"), "err");
  const held = (jobs.jobs || []).filter((j) => j.status === "held");
  let okn = 0;
  for (const j of held) {
    const r = await send({ type: "jobPrintNow", id: j.id });
    if (r.ok) okn++;
  }
  msg(okn + " of " + held.length + " held job(s) now printing", okn ? "info" : "err");
  $("heldBanner").classList.remove("show");
  setTimeout(refresh, 1500);
});

$("bOpts").addEventListener("click", () => chrome.runtime.openOptionsPage());
/* v2.8: footer Dashboard link - opens the ACTIVE target's dashboard
 * (Self PC, or the LAN PC when Share Send is on). */
$("lnkDash").addEventListener("click", (e) => {
  e.preventDefault();
  send({ type: "openHubPage", page: "/dashboard", target: "active" });
});
/* v3.1.2: Console button - opens THE ONE UI (/ui) of the ACTIVE hub
 * (local tool, or the Center PC in child-PC mode). */
$("lnkConsole").addEventListener("click", (e) => {
  e.preventDefault();
  send({ type: "openHubPage", page: "/ui", target: "active" });
});
$("lnkDebug").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: "options.html#debug" });
});
$("lnkApi").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: chrome.runtime.getURL("options.html#api") });
});
$("connect").addEventListener("click", (e) => { e.preventDefault(); refresh(); });

/* ---------- v2.0: apply UI language (en / bn / auto) ---------- */
AdvPrintI18n.currentLang().then((lang) => {
  AdvPrintI18n.apply(lang);
  $("swQueueSub").textContent = $("swQueue").checked
    ? AdvPrintI18n.t("popQueueOn") : AdvPrintI18n.t("popQueueOff");
  const off = document.body.classList.contains("off");
  $("swEnabledSub").textContent = off ? AdvPrintI18n.t("popEnabledOff")
                                      : AdvPrintI18n.t("popEnabledOn");
  // re-render the share switch sub-labels in the active language
  renderShareTxState($("swShareTx").checked);
  renderShareRxState($("swShareRx").checked, !$("swShareRx").disabled);
});

/* v2.7.0: the version badge always matches the real manifest version */
try { $("ver").textContent = "v" + chrome.runtime.getManifest().version; }
catch (_) { /* keep the hardcoded one */ }

loadSwitches();
refresh();
