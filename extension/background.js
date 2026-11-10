/* ============================================================
 * AdvPrint Pro - background service worker (MV3)
 * Bridges web pages <-> local hub (http://127.0.0.1:9235).
 * All printing is silent: the hub prints via the OS, never a dialog.
 * ============================================================ */

const DEFAULTS = {
  hubUrl: "http://127.0.0.1:9235",
  // pre-2.0 hub default - kept ONLY so upgraded old installs keep
  // working; new hubs generate a private random token and the popup
  // offers the one-click "Fix token" (loopback /token/current).
  token: "PrintHub-2024",
  defaultPrinter: "",
  enabled: true,            // MASTER SWITCH: false = AdvPrint fully off
                            // (no printing, no auto-print, no hook/API,
                            //  gray OFF badge on the toolbar icon)
  queueMode: true,          // ON  = jobs go through the hub FIFO queue
                            //      (pause/resume, ordered)
                            // OFF = hub prints each job immediately
                            //      (queue:false - no waiting in line)
  lanSend: false,           // v2.8 SHARE SEND ROUTE: ON  = print jobs go
                            //      to the LAN PC hub (hubUrlLan +
                            //      hubTokenLan - Options > LAN PC);
                            //      OFF = jobs print on THIS PC's own hub
                            //      (hubUrl). The popup toggle switches it.
  hubUrlLan: "",            // v2.8 LAN PC profile: the OTHER PC's hub URL
                            // (e.g. http://192.168.0.60:9235). Two full
                            // profiles exist: Self PC (hubUrl + token) and
                            // LAN PC (hubUrlLan + hubTokenLan).
  hubTokenLan: "",          // v2.8 the LAN PC's hub token (Options)
  hubMode: "auto",          // v3.1.2 CENTER MODE: "auto" = use the local
                            // tool's hub when it answers, otherwise the
                            // Center PC (child-PC mode). "local" = this PC
                            // only. "center" = always the Center PC.
  centerUrl: "",            // v3.1.2 the Center PC's hub URL (the one hub
                            // many child PCs connect to - the child PC
                            // needs NO AdvPrint tool, only this extension)
  centerToken: "",          // v3.1.2 the Center PC's hub token (Options)
  retryOffline: true,       // v2.0: keep jobs in the browser while the hub
                            // is unreachable and send them when it returns
  lang: "auto",             // v2.0 UI language: auto | en | bn
  hookPrint: true,          // intercept window.print() on every page
  failFallback: "tab",      // page print call failed: "tab"=open URL in new tab, "none"=stay silent
  autoPrintAllPdfs: true,   // SIMPLE MODE: any PDF opened in the browser prints silently
  closeAfterPrint: false,   // v2.8 DEFAULT OFF (was true): auto-printed URLs
                            // keep their tab open - the user opts in to
                            // closing in Options > Behavior
  contextMenu: true,        // right-click "AdvPrint Pro" menu
  badge: true,              // show ok/fail on the toolbar icon
  debugMode: false,         // v2.3 DEBUG: collect this extension's errors
                            // (JS, network, print calls) and POST them to
                            // the hub (POST /debug/report) so /debug and
                            // the Options > Debug tab can answer WHY a
                            // job did not print. Also switches the hub's
                            // verbose [DEBUG] logging on.
  printDefaults: {},        // v2.2: default print options from Options >
                            // "Default print options" (copies, pages mode,
                            // quality draft/normal/high/DPI, per_sheet,
                            // duplex, scale, margins, paper, orientation)
  apiSites: ["*"],          // v3.2.0 WEBSITE API WHITELIST - DEFAULT "*":
                            //  ALL websites may call window.advprint /
                            //  printPdfLink out of the box (the ONE UI
                            //  Rules panel shows this live). One pattern
                            //  per line to restrict, e.g.
                            //   *://www.htncr.org/*
                            //   https://reports.example.com/*
                            //  The extension's own pages are always allowed.
  rulesPaused: false,       // v3.0.5 RULE MANAGER: pause ALL auto-print
                            // rules with ONE switch. v3.0.6: the switch
                            // lives in the OPTIONS page only (Rules tab
                            // power switch + General > Power switches) -
                            // the popup row was removed. Only the HIDDEN
                            // auto work is paused - manual prints (popup
                            // button, right-click menu) keep working.
  rules: [
    {
      pattern: "*://www.htncr.org/lab/medical_reports/pdf/*",
      type: "glob",           // "glob" (1.x style) or "regex" (v2.0)
      title: "",              // v2.0: only match when the page title contains this
      printer: "",
      action: "auto",         // pdf if the URL serves a PDF, else page render
      auto: true,             // print automatically when the URL is opened
      enabled: true,          // v2.0: per-site on/off switch
      match: "url",           // v3.0.6: "url" (address matches pattern)
                              // or "content" (the PAGE CONTENT decides)
      kind: ""                // v3.0.6 content rule: "zpl" (^XA...^XZ
                              // label text), "text" (receipt / plain
                              // text page), "pdf", "image", "html"
    }
  ]
};

/* ---------------- config (managed -> local merge) ---------------- */
let CFG = null;

async function loadCfg() {
  if (CFG) return CFG;
  let managed = {};
  try { managed = await chrome.storage.managed.get(null); } catch (_) {}
  const local = await chrome.storage.local.get(null);
  CFG = Object.assign({}, DEFAULTS, local, managed);
  // managed rules fully override local rules (enterprise lockdown)
  if (managed.rules) CFG.rules = managed.rules;
  return CFG;
}

function invalidateCfg() { CFG = null; }

/* ---------------- v2.8: two hub profiles (Self PC / LAN PC) --------
 * The extension keeps TWO full hub profiles:
 *   Self PC  - hubUrl + token          (this computer's hub + printers)
 *   LAN PC   - hubUrlLan + hubTokenLan (another PC's hub, share-send)
 * Share Send Mode (lanSend) routes PRINT jobs: ON -> LAN PC, OFF ->
 * Self PC. Management calls (config, debug, token heal) always talk
 * to the Self PC hub. */
function hubBase(cfg, target) {
  if (target === "lan" && cfg.hubUrlLan) {
    return String(cfg.hubUrlLan).replace(/\/+$/, "");
  }
  return (cfg.hubUrl || DEFAULTS.hubUrl).replace(/\/+$/, "");
}

/* v3.1.2 CENTER MODE - one center PC, many child PCs.
 * A child PC installs ONLY this extension (no AdvPrint tool): when the
 * local tool is not answering, print traffic goes to the CENTER PC's
 * hub. The probe is cached for 60 s so every job does not pay a
 * timeout; the probe failure itself is fast (AbortController 1200 ms). */
let _localProbe = { t: 0, up: null };

async function localHubUp(cfg) {
  const now = Date.now();
  if (_localProbe.up !== null && now - _localProbe.t < 60000) {
    return _localProbe.up;
  }
  let up = false;
  try {
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 1200);
    const r = await fetch(hubBase(cfg, "self") + "/health",
                          { signal: ctl.signal });
    clearTimeout(to);
    up = !!r.ok;
  } catch (_) {
    up = false;
  }
  _localProbe = { t: now, up };
  return up;
}

/* The ACTIVE self hub: honors hubMode + the live local-hub probe. */
async function activeHub(cfg) {
  const mode = cfg.hubMode || "auto";
  const local = hubBase(cfg, "self");
  const center = cfg.centerUrl ? String(cfg.centerUrl).replace(/\/+$/, "") : "";
  if (mode === "local" || !center) {
    return { url: local, token: cfg.token, isCenter: false, mode };
  }
  if (mode === "center") {
    return { url: center, token: cfg.centerToken || cfg.token,
             isCenter: true, mode };
  }
  // auto: local when it answers, else the center PC (child-PC mode)
  const up = await localHubUp(cfg);
  if (up) return { url: local, token: cfg.token, isCenter: false, mode };
  return { url: center, token: cfg.centerToken || cfg.token,
           isCenter: true, mode };
}

function hubToken(cfg, target) {
  if (target === "lan" && cfg.hubUrlLan) {
    return cfg.hubTokenLan || cfg.token || "";
  }
  return cfg.token;
}

async function resolveTarget() {
  const cfg = await loadCfg();
  return (cfg.lanSend === true && cfg.hubUrlLan) ? "lan" : "self";
}

async function saveCfg(patch) {
  await chrome.storage.local.set(patch);
  invalidateCfg();
  CFG = await loadCfg();
}

/* ---------------- offline retry queue (v2.0) ------------------------ */
/* When the hub cannot be reached, jobs are kept here and flushed by a
 * 1-minute alarm as soon as /health answers again. The popup shows an
 * offline banner with the waiting count + a Retry-now button. */
const RETRY_ALARM = "advprint-retry";

async function retryQueueInfo() {
  const st = await chrome.storage.local.get({ retryQueue: [] });
  return st.retryQueue || [];
}

async function queueForRetry(payload) {
  const q = await retryQueueInfo();
  q.push({ payload, added_at: new Date().toISOString(), tries: 0 });
  await chrome.storage.local.set({ retryQueue: q.slice(-100) });
  await updateRetryBadge();
  try {
    await chrome.alarms.create(RETRY_ALARM, { periodInMinutes: 1 });
  } catch (_) {}
  console.warn("[AdvPrint] hub offline - job parked for retry (" +
               q.length + " waiting)");
}

async function flushRetries(reason) {
  const cfg = await loadCfg();
  if (cfg.enabled === false) return 0;
  const q = await retryQueueInfo();
  if (!q.length) return 0;
  let sent = 0;
  const remaining = [];
  let stopped = null;           // "auth" | "locked" | null
  for (let i = 0; i < q.length; i++) {
    const item = q[i];
    try {
      const data = await hubFetch("/print", { method: "POST",
                                              body: item.payload },
                                  await resolveTarget());
      await rememberJob({ id: data.job_id,
                          title: (item.payload && item.payload.title) || "retry",
                          status: data.status || "queued",
                          printer: "retry" });
      sent++;
    } catch (e) {
      if (e && (e.auth || e.locked)) {
        // v2.2.0 circuit breaker: STOP immediately. Every extra request
        // just feeds the hub's failure counter and (with several Chrome
        // windows on one IP) locks everyone out longer. Tries are NOT
        // burned - this is a config problem, not a dead job.
        stopped = e.auth ? "auth" : "locked";
        remaining.push(...q.slice(i));
        break;
      }
      item.tries = (item.tries || 0) + 1;
      if (item.tries < 20) remaining.push(item);   // give up after ~20 min
    }
  }
  await chrome.storage.local.set({ retryQueue: remaining });
  await updateRetryBadge();
  if (!remaining.length) {
    try { await chrome.alarms.clear(RETRY_ALARM); } catch (_) {}
  }
  if (stopped) {
    await setAuthProblem(true, stopped);
    FLUSH_BACKOFF_MIN = Math.min(FLUSH_BACKOFF_MIN * 2 || 2, 15);
    await scheduleRetryAlarm();      // slow down: 1 -> 2 -> 4 -> 8 -> 15 min
    console.warn("[AdvPrint] retry paused for " + FLUSH_BACKOFF_MIN +
                 " min (" + remaining.length + " job(s) kept)");
    return sent;
  }
  if (sent) {
    FLUSH_BACKOFF_MIN = 1;
    await setAuthProblem(false);
    console.log("[AdvPrint] " + sent + " parked job(s) delivered" +
                (reason ? " (" + reason + ")" : ""));
    await flashBadge(true, "OK");
  }
  return sent;
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm && alarm.name === RETRY_ALARM) {
    flushRetries("alarm");
  }
  if (alarm && alarm.name === VERIFY_ALARM) {
    verifyJobs();              // v2.2.1: did the job really print?
  }
});

/* v2.2.0: the moment the user fixes the token or hub URL (Options page,
 * popup Connect) clear the KEY state, reset the backoff and retry at
 * once - no need to wait for the next alarm tick. */
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.token || changes.hubUrl) {
    FLUSH_BACKOFF_MIN = 1;
    setAuthProblem(false).then(() => flushRetries("config-changed"));
  } else if (changes.authProblem && !changes.authProblem.newValue) {
    updateRetryBadge();       // KEY badge can go away
  }
});

async function updateRetryBadge() {
  const cfg = await loadCfg();
  if (!cfg.badge || cfg.enabled === false) return;
  try {
    const st = await chrome.storage.local.get({ authProblem: null });
    if (st.authProblem) {           // v2.2.0: token problem outranks count
      await chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
      await chrome.action.setBadgeText({ text: "KEY" });
      return;
    }
    const q = await retryQueueInfo();
    if (q.length) {
      await chrome.action.setBadgeBackgroundColor({ color: "#d97706" });
      await chrome.action.setBadgeText({ text: String(q.length) });
    } else {
      await chrome.action.setBadgeText({ text: "" });
    }
  } catch (_) {}
}

/* ---------------- hub client ---------------- */
class HubError extends Error {}

/* ---------------- v2.6.2: token auto-heal ----------------
 * THE #1 REASON THE EXTENSION SAID "OFFLINE" WHILE THE DESKTOP TOOL
 * SHOWED "RUNNING": the extension keeps the hub token in its storage.
 * After an update / token rotation the stored token no longer matches
 * the hub's config token -> every call answers 401 -> the popup showed
 * a misleading "OFFLINE - start the hub first".
 * Fix: the moment the hub rejects the token, ask the HUB ITSELF for
 * its current token via GET /token/current (loopback only, CORS-locked
 * since v2.6.2 - web pages can never read it). Store it and retry the
 * original call transparently. Rate-limited to one attempt per 30 s
 * so a broken setup can never hammer the hub. */
const HEAL = { last: 0, inflight: null };

function autoHealToken() {
  if (Date.now() - HEAL.last < 30000) return Promise.resolve(false);
  if (HEAL.inflight) return HEAL.inflight;
  HEAL.last = Date.now();
  HEAL.inflight = (async () => {
    try {
      const cfg = await loadCfg();
      const base = (cfg.hubUrl || DEFAULTS.hubUrl).replace(/\/+$/, "");
      const r = await fetch(base + "/token/current", { cache: "no-store" });
      if (!r.ok) return false;
      const d = await r.json();
      if (d && d.ok && d.token) {
        await chrome.storage.local.set({ token: d.token });
        invalidateCfg();
        await setAuthProblem(false);
        reportDebug("info",
                    "token auto-synced from the running hub (loopback " +
                    "pairing) - connection restored without user action");
        return true;
      }
      return false;
    } catch (_) {
      return false;              // hub unreachable / LAN hub - give up quietly
    } finally {
      HEAL.inflight = null;
    }
  })();
  return HEAL.inflight;
}

async function hubFetch(path, opts = {}, target = "self") {
  const cfg = await loadCfg();
  let base, tok;
  if (target === "lan") {
    base = hubBase(cfg, target);
    tok = hubToken(cfg, target);
  } else {
    // v3.1.2 CENTER MODE: the self target resolves through the
    // local/center ladder (probe-cached, see activeHub)
    const act = await activeHub(cfg);
    base = act.url;
    tok = act.token;
  }
  let url = base + path;
  const headers = Object.assign(
    { "X-AdvPrint-Token": tok },
    opts.body ? { "Content-Type": "application/json" } : {}
  );
  let body = opts.body ? JSON.stringify(opts.body) : undefined;
  if (opts.raw) {
    // v2.9.1 (audit P3 fix): raw binary upload - params ride the query
    // string, bytes go up as-is (no base64 inflation).
    const qs = new URLSearchParams();
    Object.entries(opts.rawQuery || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    url += (url.includes("?") ? "&" : "?") + qs.toString();
    headers["Content-Type"] = opts.contentType || "application/octet-stream";
    body = opts.raw;
  }
  const res = await fetch(url, {
    method: opts.method || "GET",
    headers: headers,
    body: body
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok || data.ok === false) {
    // v2.2.0: tag auth/lock errors so callers can stop hammering the
    // hub (every wrong request feeds its IP failure counter)
    const err = new HubError(data.error || ("HTTP " + res.status));
    err.status = res.status;
    err.auth = res.status === 401;
    err.locked = res.status === 429;
    // v2.6.2: token rejected -> try the automatic fix FIRST. When the
    // hub runs on this same PC it hands out its current token at
    // /token/current (loopback only); the original call is then
    // retried transparently, so a stale token can never again show
    // the extension as "offline" while the desktop tool is running.
    // v2.8: NEVER auto-heal against the LAN PC profile - /token/current
    // is loopback-only and would install THIS PC's token over the LAN
    // profile's own token field.
    if (res.status === 401 && target !== "lan" &&
        !path.startsWith("/token/current")) {
      reportDebug("warn",
                  "hub rejected the stored token (401) - auto token " +
                  "sync starts (" + base + ")",
                  "extension " + chrome.runtime.getManifest().version);
      if (await autoHealToken()) return hubFetch(path, opts);
    }
    // v2.3: report the failure to /debug while Debug mode is on (skip
    // /debug/report itself so reporting can never recurse into itself)
    if (!path.startsWith("/debug/report") && !DBG_SENDING) {
      reportDebug(res.status === 401 || res.status === 429 ? "warn"
                                                           : "error",
                  "hub " + (opts.method || "GET") + " " + path +
                  " -> HTTP " + res.status +
                  (data.error ? ": " + data.error : ""),
                  "extension " + chrome.runtime.getManifest().version,
                  opts.body && opts.body.job_id);
    }
    throw err;
  }
  return data;
}

/* ---------------- auth problem state (v2.2.0) -------------------
 * When the hub answers 401 (token rejected) or 429 (IP temporarily
 * locked) the extension must NOT keep retrying - with several Chrome
 * windows sharing one IP that would lock the dashboard and the other
 * windows out too. State is stored so the popup can show a banner. */
let FLUSH_BACKOFF_MIN = 1;      // alarm period: 1 -> 2 -> 4 -> 8 -> 15 min

/* ---------------- v2.3 DEBUG: client error reporting ---------------- */
/* Debug mode ON (extension Options > Settings, or the hub dashboard)
 * makes the extension report EVERY problem it hits to the hub:
 * POST /debug/report {source, level, message, context, job_id}.
 * GET /debug (or Options > Debug tab, or the dashboard Debug card)
 * then answers "when / why / where is the problem" with facts -
 * including browser-side errors that never reach hub.log. */
let DBG_SENDING = false;        // re-entry guard: reporting must never loop

async function reportDebug(level, message, context, jobId) {
  try {
    const cfg = await loadCfg();
    if (!cfg.debugMode || DBG_SENDING) return;
    DBG_SENDING = true;
    try {
      await hubFetch("/debug/report", { method: "POST", body: {
        source: "extension",
        level: level || "error",
        message: String(message || "").slice(0, 900),
        context: context == null ? "" :
                 (typeof context === "string"
                   ? context.slice(0, 1500)
                   : JSON.stringify(context).slice(0, 1500)),
        job_id: jobId || null } });
    } finally {
      DBG_SENDING = false;
    }
  } catch (_) { /* debug reporting must NEVER break printing */ }
}

// service-worker-level JS errors also land in /debug while Debug is on
self.addEventListener("error", (e) => {
  reportDebug("error", "background JS error: " + (e.message || "unknown"),
              (e.filename || "") + ":" + (e.lineno || ""));
});
self.addEventListener("unhandledrejection", (e) => {
  const r = e && e.reason;
  reportDebug("error", "background unhandled rejection: " +
              String((r && r.message) || r || "unknown").slice(0, 300));
});

async function setAuthProblem(on, why) {
  const st = await chrome.storage.local.get({ authProblem: null });
  if (on) {
    await chrome.storage.local.set({
      authProblem: { why: why || "token", at: new Date().toISOString() }
    });
    try {
      await chrome.action.setBadgeBackgroundColor({ color: "#dc2626" });
      await chrome.action.setBadgeText({ text: "KEY" });
    } catch (_) {}
    console.warn("[AdvPrint] " + (why === "locked"
      ? "hub is rate-limiting this IP (429) - backing off"
      : "hub rejected the token (401) - update it in AdvPrint options"));
  } else if (st.authProblem) {
    await chrome.storage.local.remove("authProblem");
  }
}

async function scheduleRetryAlarm() {
  try {
    await chrome.alarms.create(RETRY_ALARM,
                               { periodInMinutes: FLUSH_BACKOFF_MIN });
  } catch (_) {}
}

/* ---------------- URL pattern matching (glob + regex + contains) ----- */
function patternToRegex(pattern, type) {
  // v3.0.4: "contains" - the easiest pattern for lab staff: the URL only
  // has to CONTAIN the text (case-insensitive), nothing to learn.
  if (type === "contains") {
    return new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
  }
  if (type === "regex") return new RegExp(pattern, "i");
  let rx = "";
  for (const ch of pattern) {
    if (ch === "*") rx += ".*";
    else rx += ch.replace(/[.+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp("^" + rx + "$", "i");
}

/* v2.0 rules: type glob|regex|contains (contains since 3.0.4), optional
 * page-title filter, and a per-rule on/off switch (per-site settings).
 * First matching wins.
 * v3.0.6 CONTENT RULES: a rule can match by WHAT THE PAGE IS, not only
 * by its address. rule.match = "url" (classic, pattern decides) or
 * "content" (the detected content kind decides - see detectTabKind).
 * A content rule MAY still carry a pattern: then the URL must match it
 * too (extra filter). kind = "zpl" | "text" | "pdf" | "image" | "html". */
function isContentRule(r) {
  return !!r && (r.match === "content" ||
                 (!r.pattern && !!r.kind));   // saved without match field
}

function matchRule(url, rules, title, kind) {
  for (const r of rules || []) {
    if (!r) continue;
    if (r.enabled === false) continue;          // per-site OFF switch
    const byContent = isContentRule(r);
    if (r.pattern) {
      try {
        if (!patternToRegex(r.pattern, r.type).test(url)) continue;
      } catch (_) { continue; }
    } else if (!byContent) {
      continue;                                 // URL rule without pattern
    }
    if (byContent) {
      if (!r.kind) continue;                    // content rule needs a kind
      if (!kind || r.kind !== kind) continue;   // probed kind mismatch
    }
    if (r.title &&
        !(title || "").toLowerCase().includes(String(r.title).toLowerCase())) {
      continue;                                 // title filter miss
    }
    return r;
  }
  return null;
}

/* --------- v3.0.6: CONTENT DETECTION (what kind of page is this?) ----
 * Answers "how does AdvPrint know THIS page is ZPL / a receipt / a PDF /
 * an image" without any URL rule:
 *   1. .pdf URL or document.contentType "application/pdf"  -> "pdf"
 *   2. image URL or contentType "image/*"                  -> "image"
 *   3. the page text carries a ZPL signature (^XA ... ^XZ)  -> "zpl"
 *   4. document.contentType "text/plain"                    -> "text"
 *      (a receipt / label web tool that shows plain text)
 *   5. everything else                                      -> "html"
 * The text sample comes from the ALREADY LOADED tab (selection first,
 * then <pre>/<textarea>, then visible body text) - zero extra network
 * requests, no page JavaScript is ever injected for this. */
const ZPL_RX = /\^XA[\s\S]{0,4000}\^XZ/;      // one full label format
const ZPL_RX_LOOSE = /\^(XA|FO|FD|PQ|BC|MM|PW|LL|CI|MD|SD)/;   // any ZPL command

async function detectTabKind(tab) {
  if (!printableTab(tab)) return null;
  const url = tab.url || "";
  if (/\.pdf(\?|#|$)/i.test(url)) return "pdf";
  if (/\.(png|jpe?g|gif|webp|bmp|svg)(\?|#|$)/i.test(url)) return "image";
  let probe = null;
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        try {
          const sel = String((window.getSelection &&
                              window.getSelection()) || "").trim();
          const el = document.querySelector("pre, textarea");
          const blk = el ? (el.value !== undefined ? el.value
                                                   : el.textContent) : "";
          const body = ((document.body && document.body.innerText) || "").trim();
          return { ct: document.contentType || "",
                   text: String(sel || blk || body).slice(0, 4000) };
        } catch (_) { return { ct: "", text: "" }; }
      }
    });
    probe = res && res.result;
  } catch (_) { return null; }                 // cannot inject - no opinion
  const ct = String((probe && probe.ct) || "").toLowerCase();
  if (ct.indexOf("application/pdf") >= 0) return "pdf";
  if (ct.indexOf("image/") === 0) return "image";
  const text = String((probe && probe.text) || "");
  if (ZPL_RX.test(text) || ZPL_RX_LOOSE.test(text)) return "zpl";
  if (ct.indexOf("text/plain") === 0) return "text";
  return "html";
}

/* v3.0.6: which Action actually runs for a content rule? The rule's own
 * action is honored when it makes sense for the detected kind, otherwise
 * the kind's natural pipeline is used (a ZPL page always prints as ZPL,
 * an image always prints as an image - a wrong dropdown choice can never
 * send garbage to the printer). URL rules are untouched. */
const KIND_DEFAULT_ACTION = { zpl: "zpl", text: "raw", pdf: "pdf",
                              image: "image", html: "page" };
const KIND_OK_ACTIONS = { zpl: ["zpl"], text: ["raw"], pdf: ["pdf", "auto"],
                          image: ["image"], html: ["page", "auto"] };
function ruleActionFor(rule, kind) {
  if (!rule) return "auto";
  if (!kind || !isContentRule(rule)) return rule.action || "auto";
  const ok = KIND_OK_ACTIONS[kind];
  return (ok && ok.indexOf(rule.action) >= 0)
    ? rule.action : (KIND_DEFAULT_ACTION[kind] || "page");
}

/* v3.0.6: are there any enabled content rules at all? The auto path and
 * the manual path probe the tab ONLY then - zero cost for users who
 * still use pure URL rules. */
function hasContentRules(cfg) {
  return (cfg && cfg.rules || []).some(
    (r) => r && r.enabled !== false && isContentRule(r) && r.kind);
}

/* ------------- v3.0.5: RULE MANAGER - stats + activity log ----------
 * The lab rules work HIDDENLY (silent auto-print, no dialog). The new
 * Options > Rules tab makes that hidden work VISIBLE and CONTROLLABLE:
 * every rule keeps a run counter, the last 100 rule-triggered jobs are
 * listed in the activity log, and ONE rulesPaused switch pauses every
 * auto rule at once. Bookkeeping can never break printing. */
function ruleKey(rule) {
  return (rule && rule.id) ? String(rule.id)
    : ((rule && rule.pattern ? rule.pattern : "?") + "|" +
       (rule && rule.printer ? rule.printer : ""));
}

async function bumpRuleStats(rule, info = {}) {
  try {
    const key = ruleKey(rule);
    const st = await chrome.storage.local.get({ ruleStats: {}, ruleLog: [] });
    const stats = st.ruleStats || {};
    const s = stats[key] || { runs: 0 };
    s.runs += 1;
    s.lastRun = new Date().toISOString();
    s.lastStatus = info.status || "sent";
    s.lastError = String(info.error || "").slice(0, 160);
    stats[key] = s;
    const log = st.ruleLog || [];
    log.unshift({
      at: s.lastRun, key: key,
      pattern: (rule && rule.pattern) || "",
      printer: (rule && rule.printer) || "",
      action: (rule && rule.action) || "auto",
      mode: info.mode || "auto",          // auto | manual
      title: String(info.title || "").slice(0, 80),
      url: String(info.url || "").slice(0, 200),
      status: s.lastStatus,
      error: s.lastError
    });
    await chrome.storage.local.set({ ruleStats: stats,
                                     ruleLog: log.slice(0, 100) });
    scheduleRulesPush(6000);   // v3.2.0: runs counter reaches the ONE UI
  } catch (_) { /* bookkeeping must never break a print job */ }
}

async function getRuleState() {
  const cfg = await loadCfg();
  const st = await chrome.storage.local.get({ ruleStats: {}, ruleLog: [] });
  const rules = cfg.rules || [];
  return {
    ok: true,
    paused: cfg.rulesPaused === true,
    total: rules.length,
    enabled: rules.filter((r) => r && r.enabled !== false).length,
    auto: rules.filter((r) => r && r.enabled !== false && r.auto).length,
    stats: st.ruleStats || {},
    log: st.ruleLog || []
  };
}

/* ---------------- badge + history ---------------- */
/* Master switch state on the toolbar icon: gray OFF badge while
 * disabled, cleared when enabled. Applied on install/startup and
 * whenever the config changes. */
async function applyEnabledBadge() {
  const cfg = await loadCfg();
  try {
    if (cfg.enabled === false) {
      await chrome.action.setBadgeBackgroundColor({ color: "#64748b" });
      await chrome.action.setBadgeText({ text: "OFF" });
    } else {
      await chrome.action.setBadgeText({ text: "" });
    }
  } catch (_) {}
}

async function flashBadge(ok, text, color) {
  const cfg = await loadCfg();
  if (!cfg.badge || cfg.enabled === false) return;
  try {
    await chrome.action.setBadgeBackgroundColor(
      { color: color || (ok ? "#16a34a" : "#dc2626") });
    await chrome.action.setBadgeText({ text });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
  } catch (_) {}
}

async function rememberJob(record) {
  const st = await chrome.storage.local.get({ history: [] });
  const history = st.history || [];
  history.unshift(Object.assign({ at: new Date().toISOString() }, record));
  await chrome.storage.local.set({ history: history.slice(0, 100) });
  // v2.2.1: check back on this job so the user learns the TRUTH - the
  // green OK badge only means "the hub accepted it", not "it printed".
  if (record.id && !["saved", "canceled"].includes(record.status)) {
    await trackJobOutcome(record.id);
  }
}

/* ---------------- outcome verification (v2.2.1) --------------------- */
/* "Extension shows OK but nothing prints" - fixed by closing the loop:
 * every submitted job id is checked against the hub once a minute until
 * it reaches a final state. failed/dead -> red "!" + a notification with
 * the actual error; held -> amber "WAIT"; printed -> record the truth in
 * the extension history. No more silent gaps. */
const VERIFY_ALARM = "advprint-verify";

async function trackJobOutcome(jobId) {
  const st = await chrome.storage.local.get({ verifyIds: {} });
  const v = st.verifyIds || {};
  v[jobId] = { at: Date.now() };
  // keep the newest 30, drop anything older than 15 minutes
  const entries = Object.entries(v)
    .filter(([, meta]) => Date.now() - (meta.at || 0) < 15 * 60 * 1000)
    .sort((a, b) => b[1].at - a[1].at)
    .slice(0, 30);
  await chrome.storage.local.set({ verifyIds: Object.fromEntries(entries) });
  try {
    await chrome.alarms.create(VERIFY_ALARM, { periodInMinutes: 1 });
  } catch (_) {}
}

async function verifyJobs() {
  const st = await chrome.storage.local.get({ verifyIds: {} });
  const v = st.verifyIds || {};
  const ids = Object.keys(v).map(Number).filter((n) => n);
  if (!ids.length) {
    try { await chrome.alarms.clear(VERIFY_ALARM); } catch (_) {}
    return;
  }
  let jobs = [];
  try {
    const r = await hubFetch("/jobs?limit=50");
    jobs = r.jobs || [];
  } catch (_) {
    return;                     // hub offline - try again next tick
  }
  const byId = new Map(jobs.map((j) => [j.id, j]));
  const keep = {};
  const updates = {};
  for (const id of ids) {
    const j = byId.get(id);
    if (!j) {
      // not in the last 50 - stop tracking after the 15 min window
      if (Date.now() - (v[id].at || 0) > 15 * 60 * 1000) continue;
      keep[id] = v[id];
      continue;
    }
    if (j.status === "failed" || j.status === "dead") {
      await flashBadge(false, "!");
      reportDebug("error", "job #" + id + " NOT printed (" + j.status +
                  "): " + (j.error || "printer error"),
                  j.held_reason || "", id);
      try {
        chrome.notifications.create({
          type: "basic", iconUrl: "icons/icon128.png",
          title: "AdvPrint Pro - job NOT printed",
          message: (j.title || ("Job #" + id)) + ": " +
                   (j.error || "printer error") });
      } catch (_) {}
    } else if (j.status === "held") {
      await flashBadge(true, "WAIT", "#d97706");
    }
    if (j.status !== "queued" && j.status !== "printing" &&
        j.status !== "scheduled") {
      updates[id] = { status: j.status, error: j.error || "",
                      printer: j.printer || "" };
    } else {
      keep[id] = v[id];          // still moving - check again next tick
    }
  }
  await chrome.storage.local.set({ verifyIds: keep });
  // fold the true statuses into the extension history copy
  if (Object.keys(updates).length) {
    const h = await chrome.storage.local.get({ history: [] });
    const history = (h.history || []).map((rec) =>
      updates[rec.id]
        ? Object.assign({}, rec, { status: updates[rec.id].status,
                                   error: updates[rec.id].error,
                                   printer: updates[rec.id].printer || rec.printer })
        : rec);
    await chrome.storage.local.set({ history });
  }
  if (!Object.keys(keep).length) {
    try { await chrome.alarms.clear(VERIFY_ALARM); } catch (_) {}
  }
}

/* ---------------- print pipelines ---------------- */
async function resolvePrinter(url, title) {
  const cfg = await loadCfg();
  const rule = matchRule(url, cfg.rules, title);
  return (rule && rule.printer) || cfg.defaultPrinter || "";
}

/* "__file__" = destination File: hub saves a PDF, no paper is used */
function printerLabel(p) {
  return p === "__file__" ? "File (PDF)" : (p || "default");
}

/* v2.6.8: collapse a printer name that is the same text twice in a row
 * ("Canon LBP6230/6240Canon LBP6230/6240" -> "Canon LBP6230/6240").
 * Such a name can only come from a stale/typed-twice stored setting; it
 * used to die with "printer not found". Never raises. */
function healPrinterName(p) {
  if (typeof p !== "string" || p.length < 2) return p;
  const half = p.slice(0, Math.floor(p.length / 2));
  if (half && half === p.slice(Math.floor(p.length / 2))) return half;
  return p;
}

/* v2.6.8: only http/https/file tabs can be printed - chrome://, edge://,
 * chrome-extension://, about: and the Web Store reject script injection
 * ("Extension manifest must request permission to access this host") and
 * used to spam the hub Debug tab with that error. */
function printableTab(tab) {
  return !!(tab && /^(https?|file):/i.test(tab.url || ""));
}

function notifyNotPrintable() {
  try {
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/icon128.png",
      title: "AdvPrint Pro",
      message: "This page cannot be printed (browser-internal page: " +
               "chrome://, settings or extension page). Open the " +
               "website you want to print."
    });
  } catch (_) {}
}

function applyPrintDefaults(payload, cfg) {
  // v2.2: merge the saved "Default print options" into every job - values
  // the caller already set (page script, rule, popup) always win.
  const pd = (cfg && cfg.printDefaults) || {};
  const num = (v) => (v === "" || v == null || isNaN(parseInt(v, 10)))
    ? null : parseInt(v, 10);
  if (payload.copies == null && num(pd.copies) > 1) payload.copies = num(pd.copies);
  if (!payload.pages) {
    if (pd.pagesMode === "odd" || pd.pagesMode === "even") payload.pages = pd.pagesMode;
    else if (pd.pagesMode === "custom" && pd.pagesCustom) payload.pages = pd.pagesCustom;
  }
  if (payload.quality == null) {
    if (pd.quality === "custom" && pd.qualityCustom) payload.quality = pd.qualityCustom;
    else if (pd.quality) payload.quality = pd.quality;   // draft|normal|high|600dpi
  }
  if (payload.per_sheet == null && num(pd.perSheet) > 1) payload.per_sheet = num(pd.perSheet);
  if (payload.duplex == null && pd.duplex) payload.duplex = pd.duplex;
  if (payload.orientation == null && pd.orient) payload.orientation = pd.orient;
  if (payload.scale_pct == null && num(pd.scale) && num(pd.scale) !== 100) {
    payload.scale_pct = num(pd.scale);
  }
  if (payload.margin_mm == null && pd.margin !== "" && pd.margin != null &&
      !isNaN(parseFloat(pd.margin))) {
    payload.margin_mm = parseFloat(pd.margin);
  }
  if (payload.paper_size == null && pd.paper) payload.paper_size = pd.paper;
  return payload;
}

function hubPrint(payload, rawBytes = null) {
  if (payload.printer === "__file__") {
    payload.destination = "file";
    payload.printer = "";
  }
  // v2.6.8: a printer name typed/pasted twice ("CanonCanon") can never
  // match an installed printer - collapse it to its half before sending
  // (the hub self-heals the same way as a second safety net).
  if (payload.printer) payload.printer = healPrinterName(payload.printer);
  // Queue Mode OFF -> tell the hub to print THIS job immediately
  // (bypasses the FIFO; pause/resume does not hold it back).
  return loadCfg().then(async (cfg) => {
    if (cfg.queueMode === false) payload.queue = false;
    applyPrintDefaults(payload, cfg);
    // v2.8: the Share Send toggle decides WHERE this job prints -
    // the LAN PC hub (ON) or this PC's own hub (OFF).
    const target = await resolveTarget();
    // v2.9.1 (audit P3 fix): when rawBytes are given the document goes
    // up as a RAW application/pdf body with the params in the query
    // string - the hub accepts that natively, so the old base64 detour
    // (three full copies of every PDF inside the MV3 worker, +33%) is
    // gone. Same retry/parking/auth handling as the JSON path.
    const sendOpts = rawBytes
      ? { method: "POST", raw: rawBytes, rawQuery: payload,
          contentType: "application/pdf" }
      : { method: "POST", body: payload };
    return hubFetch("/print", sendOpts, target)
      .catch(async (e) => {
        // v2.2.0: 401 = the token is wrong. Flag it (KEY badge + popup
        // banner) and say so plainly; do NOT park the job - printing
        // cannot succeed until the token is fixed.
        if (e && e.auth) {
          await setAuthProblem(true, "token");
          reportDebug("warn", "hub rejected the token (401) - printing " +
                      "cannot succeed until the token is fixed");
          throw new HubError(target === "lan"
            ? "the LAN PC rejected the token - fix it in AdvPrint Pro " +
              "options > LAN PC (hub token field)"
            : "hub rejected the token - fix it in " +
              "AdvPrint Pro options (Hub token field)");
        }
        if (e && e.locked) {
          // v2.2.0: 429 = this IP is temporarily locked (too many bad
          // tokens from SOME client). Transient -> park and auto-retry.
          if (cfg.retryOffline !== false && payload.destination !== "file") {
            await queueForRetry(payload);
            await setAuthProblem(true, "locked");
            reportDebug("warn", "hub is rate-limiting this IP (429) - job " +
                        "parked and will retry automatically");
            throw new HubError("hub is rate-limiting this IP - job saved " +
                               "and will retry automatically");
          }
          throw new HubError("hub is rate-limiting this IP - try again " +
                             "in a few minutes");
        }
        // v2.0: network-level failure (hub down) -> park for auto-retry
        const msg = String((e && e.message) || e);
        const networkish = /failed to fetch|networkerror|load failed/i.test(msg);
        if (cfg.retryOffline !== false && networkish &&
            payload.destination !== "file") {
          await queueForRetry(payload);
          reportDebug("warn",
                      (target === "lan" ? "LAN PC hub offline" :
                       "hub offline") +
                      " - job parked for retry (" +
                      (payload.title || "untitled") + ")");
          throw new HubError(target === "lan"
            ? "LAN PC unreachable - job saved and will retry (turn " +
              "Share Send OFF to print on this PC instead)"
            : "hub offline - job saved and will retry");
        }
        reportDebug("error", "print failed: " + msg.slice(0, 300),
                    payload.title || "");
        throw e;
      });
  });
}

async function printPdfUrl(url, title, printer, extra = {}) {
  // fetch with cookies so login-protected PDFs (Laravel etc.) work
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new HubError("PDF fetch failed: HTTP " + res.status);
  return printPdfResponse(res, url, title, printer, extra);
}

async function printPdfResponse(res, url, title, printer, extra = {}) {
  const blob = await res.blob();
  const buf = new Uint8Array(await blob.arrayBuffer());
  if (buf.length < 5 || String.fromCharCode(...buf.slice(0, 5)) !== "%PDF-") {
    throw new HubError("URL did not return a PDF - got HTML? login expired?");
  }
  // v2.9.1 (audit P3 fix): RAW upload instead of base64. The params ride
  // the query string (title/printer/copies/pages/...), the PDF bytes go
  // up once, as application/pdf. extra print options still apply.
  const params = Object.assign({
    title: title || "document",
    printer: printer || "",
    source: "extension"
  }, extra);
  const data = await hubPrint(params, buf);
  // record in the shared 60 s dedupe so an auto rule will not print the
  // same URL again when a fallback tab (or the user) opens it right after
  await markPrinted(url);
  await rememberJob({ id: data.job_id, title: title || "document", url,
                      printer: printerLabel(printer),
                      status: data.status || "queued" });
  return data;
}

async function printPageDom(tab, title, printer, extra = {}) {
  // v2.9.1 (audit M8 fix): the page is CLONED and CLEANED before it is
  // sent to the hub - scripts are stripped (they re-executed inside the
  // headless renderer and could mutate/wreck the printout), <noscript>
  // junk is dropped, and a <base href> pins every relative image/CSS
  // link to the live page's URL (without it the render was a no-CSS,
  // no-image skeleton unless the site happened to use absolute URLs).
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      try {
        const clone = document.documentElement.cloneNode(true);
        clone.querySelectorAll("script, noscript").forEach((n) => n.remove());
        const head = clone.querySelector("head") || clone;
        const base = document.createElement("base");
        base.href = document.location.href;
        head.prepend(base);
        return "<!DOCTYPE html>" + clone.outerHTML;
      } catch (_) {
        return document.documentElement.outerHTML;   // old behaviour
      }
    }
  });
  const html = result && result.result;
  if (!html) throw new HubError("could not read page content");
  // v3.0.3: extra = per-rule copies/paper (rulePrintExtras) - set BEFORE
  // hubPrint applies the global print defaults, so the RULE wins.
  const data = await hubPrint(Object.assign({
    html: html,
    title: title || (tab.title || "page"),
    printer: printer || "",
    source: "extension"
  }, extra || {}));
  await markPrinted(tab.url || "");
  await rememberJob({ id: data.job_id, title: title || tab.title, url: tab.url,
                      printer: printerLabel(printer),
                      status: data.status || "queued" });
  return data;
}

async function printTab(tab, force, printerOverride) {
  // v2.6.8: browser-internal pages cannot be printed - say so instead of
  // letting the injection fail with a permission error
  if (!printableTab(tab)) { notifyNotPrintable(); return null; }
  const url = tab.url || "";
  const cfg = await loadCfg();
  let rule = matchRule(url, cfg.rules, tab.title);
  let kind = "";
  // v3.0.6: a CONTENT rule (match by what the page IS) also wins for
  // manual prints - probe the tab once, only when such rules exist
  if (!rule && hasContentRules(cfg)) {
    kind = (await detectTabKind(tab)) || "";
    if (kind) rule = matchRule(url, cfg.rules, tab.title, kind);
  }
  // v3.0.5: a rule-matched MANUAL print (Print page button, reprint box)
  // also lands in the Rule Manager run counters + activity log - the
  // manager shows the hidden work, whichever way it was triggered.
  const bumpManual = async (status, error) => {
    if (rule) await bumpRuleStats(rule, { status, mode: "manual",
                                          title: tab.title, url, error });
  };
  // v3.0.3: a rule with Action "ZPL label" / "ESC-POS receipt" turns the
  // manual "Print page" button into a label/receipt print too - the page
  // text (or the selection) goes to the hub in the printer's own
  // language for the rule's printer. No page JavaScript, ever.
  // v3.0.6: Action "Image" joins - the tab's picture prints on the rule
  // printer; content rules use the action that fits the detected kind.
  const effAction = ruleActionFor(rule, kind);
  if (force !== "pdf" && printerOverride !== "__file__" && rule &&
      (effAction === "zpl" || effAction === "raw" || effAction === "image")) {
    try {
      const outL = effAction === "image"
        ? await printTabImage(tab, rule, printerOverride || "")
        : await printTabRawLang(tab, rule, printerOverride || "");
      await bumpManual("sent");
      await flashBadge(true, "OK");
      return outL;
    } catch (eRaw) {
      await bumpManual("failed", String(eRaw.message || eRaw));
      throw eRaw;
    }
  }
  const printer = printerOverride ||
    (rule && rule.printer) || cfg.defaultPrinter || "";
  const rex = rulePrintExtras(rule);   // v3.0.3 per-rule copies/paper
  const looksPdf = /\.pdf(\?|#|$)/i.test(url);
  if (!looksPdf && force !== "pdf") {
    // render the live DOM -> hub prints via headless Chrome
    const outD = await printPageDom(tab, tab.title, printer, rex);
    await bumpManual("sent");
    await flashBadge(true, "OK");
    return outD;
  }
  const outP = await printPdfUrl(url, tab.title, printer, rex);
  await bumpManual("sent");
  await flashBadge(true, "OK");
  return outP;
}

async function printTabAuto(tab, extra = {}) {
  const url = tab.url || "";
  const printer = await resolvePrinter(url, tab.title);
  const looksPdf = /\.pdf(\?|#|$)/i.test(url);
  if (looksPdf) return printPdfUrl(url, tab.title, printer, extra);
  // v2.9.1 (audit P2 fix): ask the ALREADY-LOADED tab what its content
  // type is (document.contentType - zero network requests). The old
  // code fetched the whole URL once just to read the header, and then
  // fetched it AGAIN in printPdfUrl: two full downloads of every
  // non-.pdf PDF the auto-print path handled.
  try {
    const [probe] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => document.contentType || ""
    });
    if (probe && probe.result &&
        String(probe.result).toLowerCase().includes("application/pdf")) {
      const out = await printPdfUrl(url, tab.title, printer, extra);
      await flashBadge(true, "OK");
      return out;
    }
  } catch (_) { /* fall through to DOM render */ }
  const out = await printPageDom(tab, tab.title, printer, extra);
  await flashBadge(true, "OK");
  return out;
}

async function printSelection(text, title) {
  const cfg = await loadCfg();
  const data = await hubPrint({
    text: text,
    paper: "a4",
    title: title || "selection",
    printer: cfg.defaultPrinter || "",
    source: "extension"
  });
  await rememberJob({ id: data.job_id, title: title || "selection",
                      printer: printerLabel(cfg.defaultPrinter),
                      status: data.status || "queued" });
  await flashBadge(true, "OK");
  return data;
}

/* --------- v3.0.3: label & receipt RULE actions (no page JS) --------- */
/* A rule with Action "ZPL label" or "ESC-POS receipt" needs NO page
 * JavaScript: when the URL opens (or you press Print page), the text is
 * taken from the page - the user's text selection first, then a
 * <pre>/<textarea> block (what ZPL viewers and label web tools show),
 * then the visible body text - and pushed to the hub with an explicit
 * printer language. The hub streams ZPL byte-for-byte to the rule's
 * printer (the Zebra) or builds an ESC/POS receipt (auto cut) for the
 * thermal printer. The per-rule printer ALWAYS wins over the Print
 * destination card (the hub gives the per-job printer name priority),
 * so the lab's A4/A5 report printer and the Zebra keep printing side by
 * side without flipping any card. */
function rulePrintExtras(rule) {
  const ex = {};
  if (rule) {
    const c = parseInt(rule.copies, 10);
    if (c >= 1) ex.copies = c;                  // per-rule copies
    if (rule.paper) ex.paper_size = rule.paper; // A4/A5/... (PDF/page jobs)
  }
  return ex;
}

async function printTabRawLang(tab, rule, printerOverride) {
  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      try {
        const sel = String((window.getSelection &&
                            window.getSelection()) || "").trim();
        if (sel) return sel;                     // 1) user selection
        const el = document.querySelector("pre, textarea");
        const t = el ? (el.value !== undefined ? el.value
                                               : el.textContent) : "";
        if (t && t.trim()) return t.trim();      // 2) raw text block
        return ((document.body && document.body.innerText) ||
                "").trim();                      // 3) visible text
      } catch (_) { return ""; }
    }
  });
  const text = String((res && res.result) || "").trim();
  if (!text) {
    throw new HubError("label rule found no text on the page");
  }
  return printRawText(text, rule, tab, printerOverride);
}

async function printRawText(text, rule, tab, printerOverride) {
  const lang = rule.action === "zpl" ? "zpl" : "escpos";
  // safety net: text without a single ^ command would make the Zebra
  // print garbage - say so instead of wasting labels
  if (lang === "zpl" && !text.includes("^")) {
    throw new HubError("this page does not look like ZPL - no ^ commands " +
                       "found (ZPL labels start with ^XA)");
  }
  const payload = {
    text: text,
    lang: lang,
    title: (tab && (tab.title || "label")) || "label",
    printer: printerOverride || rule.printer || "",
    source: "extension"
  };
  const copies = parseInt(rule.copies, 10);
  if (copies >= 1) payload.copies = copies;
  const data = await hubPrint(payload);
  await markPrinted(tab ? tab.url || "" : "");
  await rememberJob({ id: data.job_id, title: payload.title,
                      url: tab ? tab.url : "",
                      printer: printerLabel(payload.printer),
                      status: data.status || "queued", lang: lang });
  return data;
}

/* --------- v3.0.6: IMAGE printing (photo / scan tabs) ----------------
 * A rule with kind "image" (or Action "Image") prints the picture the
 * tab is showing: the image is downloaded with the page's login cookies
 * and handed to the hub as image_base64 (the same route the screenshot
 * uses) - the hub rasterizes it for the printer. If the direct download
 * fails (hotlink protection, expired URL), the visible tab itself is
 * captured as a fallback, so what you see is what prints. */
async function printTabImage(tab, rule, printerOverride) {
  const url = (tab && tab.url) || "";
  let b64 = "";
  try {
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const buf = new Uint8Array(await res.arrayBuffer());
    let bin = "";
    const CH = 0x8000;
    for (let i = 0; i < buf.length; i += CH) {
      bin += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
    }
    b64 = btoa(bin);
  } catch (_) {
    try {
      const shot = await chrome.tabs.captureVisibleTab(
        tab.windowId, { format: "png" });
      b64 = String(shot || "").split(",")[1] || "";
    } catch (_) { /* both failed - report below */ }
  }
  if (!b64) throw new HubError("could not read the image on this tab");
  const payload = {
    image_base64: b64,
    title: (tab && (tab.title || "image")) || "image",
    printer: printerOverride || (rule && rule.printer) || "",
    source: "extension"
  };
  const copies = parseInt(rule && rule.copies, 10);
  if (copies >= 1) payload.copies = copies;
  const data = await hubPrint(payload);
  await markPrinted(url);
  await rememberJob({ id: data.job_id, title: payload.title, url: url,
                      printer: printerLabel(payload.printer),
                      status: data.status || "queued" });
  return data;
}

async function printScreenshot(windowId) {
  const cfg = await loadCfg();
  const dataUrl = await chrome.tabs.captureVisibleTab(windowId, {
    format: "jpeg", quality: 92
  });
  const b64 = dataUrl.split(",")[1] || "";
  const data = await hubPrint({
    image_base64: b64,
    landscape: true,
    title: "screenshot",
    printer: cfg.defaultPrinter || "",
    source: "extension"
  });
  await rememberJob({ id: data.job_id, title: "screenshot",
                      printer: printerLabel(cfg.defaultPrinter),
                      status: data.status || "queued" });
  await flashBadge(true, "OK");
  return data;
}

/* ---------------- auto-print on URL open (deduped 60 s) ---------------- */
/* After a rule auto-prints a URL, close the tab (if closeAfterPrint is on
 * and the tab still shows a rule-matching URL). Open URL -> paper comes
 * out -> tab disappears: zero browser view. */
async function maybeCloseTab(tabId, force) {
  const cfg = await loadCfg();
  if (!cfg.closeAfterPrint) return;
  setTimeout(async () => {
    try {
      const t = await chrome.tabs.get(tabId);
      if (force || matchRule(t.url || "", (await loadCfg()).rules)) {
        await chrome.tabs.remove(tabId);
      }
    } catch (_) { /* tab already gone */ }
  }, 800);
}

/* shared 60 s print dedupe - fed by auto rules AND manual prints
 * (printPdfUrl / printPageDom), so the same URL is never printed twice
 * within a minute no matter which path delivered it */
async function printedRecently(url) {
  const st = await chrome.storage.session.get({ seen: {} });
  const seen = st.seen || {};
  const now = Date.now();
  const fresh = !!(url && seen[url] && now - seen[url] < 60000);
  // prune
  for (const k of Object.keys(seen)) {
    if (now - seen[k] > 300000) delete seen[k];
  }
  return { seen, now, fresh };
}

async function markPrinted(url) {
  if (!url || !/^https?:/i.test(url)) return;
  const { seen, now } = await printedRecently(url);
  seen[url] = now;
  await chrome.storage.session.set({ seen });
}

async function shouldAutoPrint(url, title, kind) {
  const cfg = await loadCfg();
  // v3.0.6: kind (when given) lets CONTENT rules match; without it only
  // URL rules are considered (no tab probe happened yet)
  const rule = matchRule(url, cfg.rules, title, kind);
  if (!rule || !rule.auto) return null;
  if (cfg.rulesPaused) return null;   // v3.0.5: ALL auto rules paused
  const { seen, now, fresh } = await printedRecently(url);
  if (fresh) return null;
  seen[url] = now;
  await chrome.storage.session.set({ seen });
  return rule;
}

chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== "complete" || !tab || !/^https?:/i.test(tab.url || "")) return;
  try {
    const cfg0 = await loadCfg();
    if (cfg0.enabled === false) return;      // master switch OFF - do nothing
    // v3.0.6 two-pass matching:
    //   pass 1 - URL rules (no tab probe, as before)
    //   pass 2 - CONTENT rules: only when such rules exist, the tab is
    //            probed ONCE (content type + text sample) and the kind
    //            decides - "any page with ^XA -> Zebra" etc.
    let rule = await shouldAutoPrint(tab.url, tab.title);
    let kind = "";
    if (!rule && hasContentRules(cfg0)) {
      kind = (await detectTabKind(tab)) || "";
      if (kind) {
        rule = await shouldAutoPrint(tab.url, tab.title, kind);
      }
    }
    if (rule) {
      const printer = rule.printer || (await loadCfg()).defaultPrinter || "";
      const rex = rulePrintExtras(rule);       // v3.0.3 copies/paper
      // v3.0.6: content rules run the pipeline that FITS the detected
      // kind (ZPL page -> ZPL stream, image tab -> image print, ...);
      // URL rules keep their own Action exactly as configured.
      const effAction = ruleActionFor(rule, kind);
      try {
        if (effAction === "page") {
          await printPageDom(tab, tab.title, printer, rex);
        } else if (effAction === "pdf") {
          await printPdfUrl(tab.url, tab.title, printer, rex);
        } else if (effAction === "zpl" || effAction === "raw") {
          // v3.0.3: label/receipt rule - page text goes to the hub in the
          // printer's own language (ZPL verbatim / ESC-POS built)
          await printTabRawLang(tab, rule, printer);
        } else if (effAction === "image") {
          // v3.0.6: image rule - the tab's picture prints on the rule
          // printer (cookie download, visible-tab capture fallback)
          await printTabImage(tab, rule, printer);
        } else {
          await printTabAuto(tab, rex);
        }
        // v3.0.5: the Rule Manager shows this hidden hit (run counter
        // + activity log) - success and failure both, never silently
        await bumpRuleStats(rule, { status: "sent", mode: "auto",
                                    title: tab.title, url: tab.url });
      } catch (eRule) {
        await bumpRuleStats(rule, { status: "failed", mode: "auto",
                                    title: tab.title, url: tab.url,
                                    error: String(eRule.message || eRule) });
        throw eRule;
      }
      await flashBadge(true, "OK");
      // v3.0.6: a content-rule hit closes the tab directly (force) -
      // maybeCloseTab re-matches by URL only and would never see a
      // kind-only rule. closeAfterPrint stays the user's opt-in switch.
      await maybeCloseTab(tabId, !!kind);
      return;
    }
    /* ---- SIMPLE MODE (v1.1.9): ANY pdf opened in the browser prints
     * silently and its tab closes. No rules, no setup. PDF URLs (.pdf)
     * are printed directly; any other URL is content-type checked with
     * login cookies. The shared 60 s dedupe stops double prints when the
     * page's own button already printed the same URL. */
    const cfg = await loadCfg();
    if (!cfg.autoPrintAllPdfs) return;
    const { fresh } = await printedRecently(tab.url);
    const looksPdf = /\.pdf(\?|#|$)/i.test(tab.url);
    let res = null;
    if (!looksPdf) {
      if (fresh) return;   // just printed another way, and not even a .pdf URL
      try {
        res = await fetch(tab.url, { credentials: "include" });
      } catch (_) { return; }
      const ct = (res.ok ? res.headers.get("content-type") || "" : "").toLowerCase();
      if (!ct.includes("application/pdf")) return;   // a normal page - ignore
    }
    if (fresh) { await maybeCloseTab(tabId, true); return; }  // printed <60 s ago: just close the viewer
    const printer = cfg.defaultPrinter || "";
    if (looksPdf) {
      await printPdfUrl(tab.url, tab.title, printer);
    } else {
      await printPdfResponse(res, tab.url, tab.title, printer);
    }
    await flashBadge(true, "OK");
    await maybeCloseTab(tabId, true);
  } catch (e) {
    await flashBadge(false, "!");
    await rememberJob({ title: "AUTO " + (tab.title || tab.url),
                        url: tab.url, status: "failed", error: String(e.message || e) });
    reportDebug("error", "auto-print failed: " + String(e.message || e)
                .slice(0, 300), tab.url || "");
    console.warn("[AdvPrint] auto-print failed:", e);
  }
});

/* ---------------- window.print() hook + page API bridge ---------------- */
/* Legacy-Chrome safety net: registerContentScripts(world:"MAIN") needs
 * Chrome 111+. For anything older, push hook.js into every tab at commit
 * time. chrome.scripting injection is browser-initiated, so page CSP
 * cannot block it (unlike <script> tag injection - never use that). */
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== "loading" || !/^https?:/i.test(tab.url || "")) return;
  try {
    const cfg = await loadCfg();
    // Master switch OFF -> inject NOTHING: no window.print() hook, no
    // window.advprint API, nothing. Pages keep their native behavior.
    if (cfg.enabled === false) return;
    // v1.1.6: api.js (window.advprint + global printPdfLink) is injected
    // ALWAYS; hook.js (window.print interception) follows the toggle.
    const files = cfg.hookPrint
      ? ["content/hook.js", "content/api.js"]
      : ["content/api.js"];
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files,
      world: "MAIN"
    });
  } catch (_) { /* restricted page or injection unsupported */ }
});

async function injectIntoOpenTabs() {
  // Pages opened BEFORE registration have nothing yet - push the scripts
  // into every open http(s) tab now. All scripts are idempotent, so
  // re-running them is safe. api.js goes in regardless of the hook toggle
  // so window.advprint / printPdfLink stay global (v1.1.6).
  const cfg = await loadCfg();
  if (cfg.enabled === false) return;         // master switch OFF
  let tabs = [];
  try {
    tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
  } catch (_) { return; }
  for (const tab of tabs) {
    if (!tab || !tab.id) continue;
    const files = cfg.hookPrint
      ? ["content/hook.js", "content/api.js"]
      : ["content/api.js"];
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        files,
        world: "MAIN"
      });
    } catch (_) { /* restricted page - per-navigation fallback covers the rest */ }
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        files: ["content/relay.js"]
      });
    } catch (_) {}
  }
}

async function applyHook() {
  const cfg = await loadCfg();
  // MASTER SWITCH OFF: pull out every registration and inject nothing.
  // Enabled again -> applyHook re-registers what the toggles ask for.
  if (cfg.enabled === false) {
    try {
      const regs = await chrome.scripting.getRegisteredContentScripts();
      const ids = regs.map((r) => r.id)
        .filter((id) => id === "advprint-api" || id === "advprint-hook");
      if (ids.length) {
        await chrome.scripting.unregisterContentScripts({ ids });
      }
    } catch (_) {}
    return;
  }
  const wanted = !!cfg.hookPrint;
  const existing = await chrome.scripting.getRegisteredContentScripts();
  const hasApi = existing.some((s) => s.id === "advprint-api");
  const hookReg = existing.find((s) => s.id === "advprint-hook");
  // legacy (<=1.1.5) registration bundles api.js into advprint-hook
  const legacy = !!hookReg && (hookReg.js || []).includes("content/api.js");

  // v1.1.6: API registration must ALWAYS exist - window.advprint and the
  // global printPdfLink() one-liner work even with interception disabled.
  if (!hasApi) {
    try {
      await chrome.scripting.registerContentScripts([{
        id: "advprint-api",
        matches: ["<all_urls>"],
        js: ["content/api.js"],
        runAt: "document_start",
        world: "MAIN",
        allFrames: true,
        persistAcrossSessions: true
      }]);
    } catch (_) { /* older Chrome: the per-navigation fallback covers it */ }
  }

  // migrate the legacy combined registration to hook-only
  if (legacy) {
    try {
      await chrome.scripting.unregisterContentScripts({ ids: ["advprint-hook"] });
    } catch (_) {}
  }

  // hook.js strictly follows the "Print interception" toggle
  if (wanted && (legacy || !hookReg)) {
    try {
      await chrome.scripting.registerContentScripts([{
        id: "advprint-hook",
        matches: ["<all_urls>"],
        js: ["content/hook.js"],
        runAt: "document_start",
        world: "MAIN",
        allFrames: true,
        persistAcrossSessions: true
      }]);
    } catch (_) { /* older Chrome: the per-navigation fallback below takes over */ }
  } else if (!wanted && hookReg && !legacy) {
    try {
      await chrome.scripting.unregisterContentScripts({ ids: ["advprint-hook"] });
    } catch (_) {}
  }
  await injectIntoOpenTabs();
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      switch (msg && msg.type) {
        case "hookPrint": {
          // window.print() was called on a page -> print that page silently
          const hcfg = await loadCfg();
          if (hcfg.enabled === false) {
            reply({ ok: false, error: "AdvPrint is disabled - enable it in the popup (click the toolbar icon)" });
            break;
          }
          if (!hcfg.hookPrint) {
            reply({ ok: false,
                     error: "window.print() interception is OFF - turn the " +
                            "window.print switch in the Console (Power Switches)" });
            break;
          }
          const tab = sender.tab ||
            (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
          const out = await printTabAuto(tab);
          reply({ ok: true, job_id: out.job_id });
          break;
        }
        case "api": {
          // window.advprint developer API (see content/api.js)
          // v2.9.1 (audit H3 fix): the sender page is now checked against
          // the Website API allowlist inside handleApi
          reply(await handleApi(msg, sender));
          break;
        }
        case "printTab": {
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "AdvPrint is disabled - enable it in the popup (toolbar icon)" });
            break;
          }
          const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
          // msg.dest === "file" -> save as PDF instead of printing on paper
          const over = msg.dest === "file" ? "__file__" : undefined;
          reply({ ok: true, ...(await printTab(tab, msg.force, over)) });
          break;
        }
        case "printPdfUrl": {
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "AdvPrint is disabled - enable it in the popup (toolbar icon)" });
            break;
          }
          const printer = await resolvePrinter(msg.url, msg.title);
          // v3.0.3: a matching rule's copies/paper ride along with the
          // reprint, so the "Reprint a PDF link" box prints on the SAME
          // printer/paper as the auto rule would
          const rex = rulePrintExtras(
            matchRule(msg.url, (await loadCfg()).rules, msg.title));
          const out = await printPdfUrl(msg.url, msg.title, printer, rex);
          reply({ ok: true, ...out });
          break;
        }
        case "printSelection":
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "AdvPrint is disabled - enable it in the popup (toolbar icon)" });
            break;
          }
          reply({ ok: true, ...(await printSelection(msg.text, msg.title)) });
          break;
        case "printScreenshot": {
          if ((await loadCfg()).enabled === false) {
            reply({ ok: false, error: "AdvPrint is disabled - enable it in the popup (toolbar icon)" });
            break;
          }
          const win = await chrome.windows.getCurrent();
          reply({ ok: true, ...(await printScreenshot(win.id)) });
          break;
        }
        case "hubStatus": {
          // v2.6.2: structured failure - the popup must be able to tell
          // "hub not reachable" (real offline) from "hub answered 401"
          // (token mismatch - hub is RUNNING). Before this, any 401
          // landed here as a generic error and the popup showed a
          // misleading "OFFLINE - start the hub first".
          // v2.6.4: third state "slow" - the hub is LISTENING but
          // /health did not answer within 8 s (still starting).
          // v2.8: TWO hubs are probed - the SELF hub (always, it owns
          // Share Receive + config) and, when Share Send routes there,
          // the LAN PC hub. The active print target answers first in
          // the reply; self facts ride along as self_*.
          const probe = async (base) => {
            const ctl = new AbortController();
            const timer = setTimeout(() => ctl.abort(), 8000);
            try {
              const r = await fetch(base.replace(/\/+$/, "") + "/health",
                                    { cache: "no-store", signal: ctl.signal });
              const d = await r.json();
              return d && d.ok ? d
                : { ok: false, reason: "offline", error: "HTTP " + r.status };
            } catch (e) {
              const slow = e && e.name === "AbortError";
              return { ok: false,
                       reason: slow ? "slow"
                         : e && e.locked ? "locked"
                         : e && e.auth ? "auth"
                         : "offline",
                       error: slow ? "hub is listening but /health did not "
                                     + "answer within 8 s - still starting"
                                   : (e && e.message) || String(e) };
            } finally {
              clearTimeout(timer);
            }
          };
          try {
            const cfgS = await loadCfg();
            const lanUsed = cfgS.lanSend === true && !!cfgS.hubUrlLan;
            const selfSt = await probe(cfgS.hubUrl || DEFAULTS.hubUrl);
            let out;
            if (lanUsed) {
              const lanSt = await probe(cfgS.hubUrlLan);
              out = Object.assign({}, lanSt, {
                lan_used: true,
                lan_url: cfgS.hubUrlLan,
                lan_ok: lanSt.ok,
                lan_reason: lanSt.reason || "",
                self_ok: selfSt.ok,
                self_version: selfSt.version || "",
                self_share_lan: selfSt.share_lan,
                self_paused: selfSt.paused,
                ok: lanSt.ok });
              if (!lanSt.ok && selfSt.ok) {
                out.error = "the LAN PC is not reachable (" +
                  (lanSt.error || lanSt.reason || "offline") + ") - " +
                  "the Self PC hub is fine; turn Share Send OFF to " +
                  "print on this PC";
              }
            } else {
              out = Object.assign({}, selfSt, {
                lan_used: false,
                self_ok: selfSt.ok,
                self_share_lan: selfSt.share_lan });
            }
            reply(out);
          } catch (e) {
            reply({ ok: false, reason: "offline",
                    error: (e && e.message) || String(e) });
          }
          break;
        }
        case "retryInfo": {
          const q = await retryQueueInfo();
          reply({ ok: true, count: q.length });
          break;
        }
        case "flushRetries": {
          const sent = await flushRetries("manual");
          reply({ ok: true, sent });
          break;
        }
        case "hubPrinters":
          reply(await hubFetch("/printers"));
          break;
        case "hubState":
          /* v3.1.2 CENTER MODE status for the popup + options page */
          {
            const c = await loadCfg();
            const act = await activeHub(c);
            reply({ ok: true, mode: act.mode, isCenter: act.isCenter,
                    activeUrl: act.url,
                    localUrl: hubBase(c, "self"),
                    centerUrl: c.centerUrl || "",
                    localUp: await localHubUp(c) });
          }
          break;
        case "hubPeers":
          reply(await hubFetch("/peers"));
          break;
        case "hubCaps":
          reply(await hubFetch("/printers/" +
            encodeURIComponent(msg.name || "") + "/capabilities"));
          break;
        case "hubConfigGet":
          reply(await hubFetch("/config"));
          break;
        case "hubConfigSet":
          reply(await hubFetch("/config", { method: "POST",
                                            body: msg.patch || {} }));
          break;
        case "tokenDetect": {
          /* v2.6 one-click token fix: ask the hub for its current token.
           * The hub answers ONLY to loopback (the hub PC itself), so this
           * works for a local hub and fails cleanly for a LAN hub. */
          const base = (msg.hubUrl ||
            (await loadCfg()).hubUrl || "http://127.0.0.1:9235").replace(/\/+$/, "");
          try {
            const r = await fetch(base + "/token/current", {
              cache: "no-store" });
            if (!r.ok) {
              reply({ ok: false, error: r.status === 403
                ? "The hub only gives the token to programs on the hub PC itself. Open it there, or paste the token manually."
                : "HTTP " + r.status });
              break;
            }
            const d = await r.json();
            if (d && d.ok && d.token) {
              await chrome.storage.local.set({ token: d.token });
              CFG = null; // reload on next use
              reply({ ok: true, token: d.token, version: d.version });
            } else {
              reply({ ok: false, error: "hub gave no token" });
            }
          } catch (e) {
            reply({ ok: false,
              error: "hub not reachable (" + e.message + ") - start the hub first" });
          }
          break;
        }
        case "queueShift": {
          // v2.7.0 gate, v2.8 wording: Share Send OFF = nothing leaves
          // this browser toward another PC (shift included).
          const cfgQ = await loadCfg();
          if (cfgQ.lanSend !== true) {
            reply({ ok: false,
                     error: "Share Send Mode is OFF - turn it on in the " +
                            "Console (LAN tab > Share Send Mode) to " +
                            "shift jobs to another PC" });
            break;
          }
          reply(await hubFetch("/queue/shift", { method: "POST", body: {
            scope: msg.scope || "all",
            ids: msg.ids || [],
            target: msg.target || "",
            target_token: msg.targetToken || "" } }));
          break;
        }
        case "jobBulkReprint":
          // v2.7.0: History panel "Reprint selected" / "Reprint all
          // non-printed" - one POST, per-job results.
          reply(await hubFetch("/jobs/bulk-reprint", { method: "POST",
            body: { ids: msg.ids || [], scope: msg.scope || "",
                    reason: msg.reason || "" } }));
          break;
        case "historyClear":
          // v2.7.0: wipe FINISHED jobs from the hub history (waiting
          // jobs are never touched).
          reply(await hubFetch("/history/clear", { method: "POST",
                                                  body: {} }));
          break;
        case "hubJobs": {
          // v2.8: Recent jobs follow the ACTIVE print target - when
          // Share Send is ON the list shows the LAN PC's jobs.
          const jt = msg.target === "print" ? await resolveTarget() : "self";
          reply(await hubFetch("/jobs?limit=" + (msg.limit || 100), {}, jt));
          break;
        }
        case "queueAction": {
          // v2.8: pause/resume follows the ACTIVE print target too
          const qt = msg.target === "print" ? await resolveTarget() : "self";
          reply(await hubFetch("/queue/" + msg.action,
                               { method: "POST", body: {} }, qt));
          break;
        }
        case "openHubPage": {
          // v2.8: open the dashboard / audit log of Self PC or LAN PC
          // ("Open hub dashboard & Open audit log self and lan managed
          // separately"). msg.page = "/dashboard" | "/audit" | "/docs";
          // msg.target = "self" | "lan" | "active".
          const cfgO = await loadCfg();
          const t = msg.target === "lan" ? "lan"
                  : msg.target === "active" ? await resolveTarget()
                  : "self";
          let baseO, tokO;
          if (t === "lan") {
            baseO = hubBase(cfgO, "lan");
            tokO = cfgO.hubTokenLan || cfgO.token || "";
          } else if (msg.target === "active") {
            // v3.1.2 CENTER MODE: "active" resolves through the
            // local/center ladder (child PC -> Center PC hub)
            const act = await activeHub(cfgO);
            baseO = act.url;
            tokO = act.token;
          } else {
            baseO = hubBase(cfgO, "self");
            tokO = cfgO.token || "";
          }
          chrome.tabs.create({ url: baseO + (msg.page || "/dashboard") +
            "?token=" + encodeURIComponent(tokO) });
          reply({ ok: true, target: t, base: baseO });
          break;
        }
        case "jobAction":
          reply(await hubFetch(`/jobs/${msg.id}/${msg.action}`,
                               { method: "POST", body: {} }));
          break;
        case "jobPrintNow":
          // v2.2.1: force one job out right now - bypasses the global
          // pause and the printer-status hold ("nothing prints" remedy)
          reply(await hubFetch(`/jobs/${msg.id}/print-now`,
                               { method: "POST", body: {} }));
          break;
        case "hubDebug":
          // v2.3: full debug report (problems + client reports)
          reply(await hubFetch("/debug"));
          break;
        case "debugTestReport":
          // v2.3: prove the pipeline works - send one test report, then
          // the Debug tab can show it immediately
          await reportDebug("info",
            "test report from the extension - if you can read this in " +
            "the Debug tab, error reporting works end to end",
            "sent from Options > Debug");
          reply({ ok: true });
          break;
        case "jobRetry":
          reply(await hubFetch(`/jobs/${msg.id}/retry`, {
            method: "POST",
            body: { printer: msg.printer || "", reason: msg.reason || "" } }));
          break;
        case "jobReprint":
          reply(await hubFetch(`/jobs/${msg.id}/reprint`, {
            method: "POST",
            body: { reason: msg.reason || "" } }));
          break;
        case "saveCfg":
          await saveCfg(msg.patch || {});
          await applyHook();
          await rebuildMenus();
          await applyEnabledBadge();
          if (msg.patch && msg.patch.debugMode !== undefined) {
            // v2.3: ONE Debug switch drives BOTH sides - the extension's
            // error reporting AND the hub's verbose logging / client
            // collection (GET /debug shows both). Best effort: the hub
            // may be offline right now.
            hubFetch("/config", { method: "POST",
                                  body: { debug: !!msg.patch.debugMode } })
              .catch(() => {});
          }
          reply({ ok: true });
          break;
        case "getCfg":
          reply({ ok: true, cfg: await loadCfg() });
          break;
        case "ruleState": {
          // v3.0.5 RULE MANAGER: pause state, run counters, activity log
          reply(await getRuleState());
          break;
        }
        case "clearRuleLog": {
          // v3.0.5: wipe the activity log (msg.stats also resets the
          // per-rule run counters)
          const clr = { ruleLog: [] };
          if (msg.stats) clr.ruleStats = {};
          await chrome.storage.local.set(clr);
          reply({ ok: true });
          break;
        }
        case "testRuleUrl": {
          // v3.0.5: the Rules-tab simulator - WHICH rule would fire, on
          // which printer, with which action? It only MATCHES; nothing
          // is printed, no tab is touched, the dedupe is not fed.
          // v3.0.6: the simulator now also SNIFFS THE CONTENT - the URL
          // is fetched once with login cookies (PDF/image/text types are
          // read from the headers, the first bytes are checked for ^XA)
          // so URL rules AND content rules are reported. If the fetch
          // fails (login page, offline) only URL rules are matched and
          // the answer says so.
          const cfgT = await loadCfg();
          let kindT = String(msg.kind || "");
          let kindSrc = kindT ? "given" : "";
          let contentType = "";
          if (!kindT && /^https?:/i.test(String(msg.url || ""))) {
            try {
              const res = await fetch(String(msg.url),
                                      { credentials: "include" });
              const ct = (res.headers.get("content-type") || "")
                .toLowerCase();
              contentType = ct.split(";")[0];
              if (ct.indexOf("application/pdf") >= 0) {
                kindT = "pdf";
              } else if (ct.indexOf("image/") === 0) {
                kindT = "image";
              } else {
                const sample = (await res.text()).slice(0, 4000);
                if (ZPL_RX.test(sample) || ZPL_RX_LOOSE.test(sample)) {
                  kindT = "zpl";
                } else if (ct.indexOf("text/plain") === 0) {
                  kindT = "text";
                } else {
                  kindT = "html";
                }
              }
              kindSrc = "fetched";
            } catch (_) { kindSrc = "fetch-failed"; }
          }
          const rT = matchRule(String(msg.url || ""), cfgT.rules,
                               String(msg.title || ""), kindT || undefined);
          reply({ ok: true, matched: !!rT, rule: rT || null,
                  index: rT ? cfgT.rules.indexOf(rT) + 1 : 0,
                  printer: rT ? (rT.printer || cfgT.defaultPrinter || "")
                              : (cfgT.defaultPrinter || ""),
                  simplePdf: cfgT.autoPrintAllPdfs !== false,
                  paused: cfgT.rulesPaused === true,
                  kind: kindT, kindSrc: kindSrc,
                  contentType: contentType });
          break;
        }
        case "testRuleText": {
          // v3.0.6: paste label / receipt text - the simulator tells you
          // WHICH content rule would fire for it (and as what). Nothing
          // is printed, no URL is touched.
          const cfgT = await loadCfg();
          const text = String(msg.text || "");
          const kindTx = ZPL_RX.test(text) || ZPL_RX_LOOSE.test(text)
            ? "zpl" : "text";
          const rTx = matchRule("", cfgT.rules, "", kindTx);
          reply({ ok: true, kind: kindTx, matched: !!rTx,
                  rule: rTx || null,
                  index: rTx ? cfgT.rules.indexOf(rTx) + 1 : 0,
                  printer: rTx ? (rTx.printer || cfgT.defaultPrinter || "")
                               : (cfgT.defaultPrinter || ""),
                  paused: cfgT.rulesPaused === true });
          break;
        }
        default:
          reply({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      reply({ ok: false, error: String(e.message || e) });
    }
  })();
  return true; // async reply
});

/* ---------------- v2.9.1 (audit H3 fix): Website API allowlist ----
 * window.advprint / printPdfLink used to be injectable into <all_urls>
 * and callable by EVERY http(s) page - any tab you had open could print
 * documents, read the job history and pass raw PDFs to the hub. The API
 * is now restricted to cfg.apiSites (Options > Website API): the page's
 * origin must match one entry. Patterns are like the auto-print rules:
 *   *://www.htncr.org/*      scheme wildcard + host + path
 *   https://reports.example.com/*
 *   reports.example.com      bare host = any scheme
 *   *.example.org            subdomain wildcard
 */
function apiSiteAllowed(origin, sites) {
  if (!sites || !sites.length) return false;
  let host = "", scheme = "";
  try {
    const u = new URL(origin || "");
    host = u.hostname.toLowerCase();
    scheme = (u.protocol || "").replace(":", "");
  } catch (_) { return false; }
  if (!host) return false;
  for (const raw of sites) {
    const pat = String(raw || "").trim().toLowerCase();
    if (!pat) continue;
    let pScheme = null, rest = pat;
    const m = pat.match(/^([a-z*]+):\/\/(.*)$/);
    if (m) { pScheme = m[1]; rest = m[2]; }
    const pHost = rest.split("/")[0];
    const schemeOk = !pScheme || pScheme === "*" || pScheme === scheme;
    const hostOk = pHost === "*" || pHost === host ||
      (pHost.startsWith("*.") &&
       (host === pHost.slice(2) ||
        host.endsWith("." + pHost.slice(2))));
    if (schemeOk && hostOk) return true;
  }
  return false;
}

async function handleApi(msg, sender) {
  const cfg = await loadCfg();
  const req = msg.payload || {};
  // v2.9.1 (audit H3 fix): the caller page must be on the Website API
  // allowlist. The extension's own pages (options/popup) are always
  // trusted. With an EMPTY list the page API is simply OFF everywhere.
  const sOrigin = String((sender && (sender.origin || sender.url)) || "");
  const ownExt = sOrigin.startsWith("chrome-extension://") ||
                 sOrigin.startsWith("moz-extension://") ||
                 sOrigin.startsWith("safari-web-extension://");
  if (!ownExt) {
    if (!apiSiteAllowed(sOrigin, cfg.apiSites)) {
      throw new HubError(
        "AdvPrint page API is not allowed for " +
        (sOrigin || "this page") +
        " - add the site in AdvPrint Pro Options > Website API");
    }
  }
  // read-only calls stay available even while disabled; printing calls
  // are refused so a disabled AdvPrint never prints from a page
  const PRINT_FNS = ["printPage", "printPdf", "print"];
  if (PRINT_FNS.includes(req.fn) && cfg.enabled === false) {
    throw new HubError("AdvPrint is disabled - enable it in the Console (Power Switches)");
  }
  switch (req.fn) {
    case "status":
      return await hubFetch("/health");
    case "printers":
      return await hubFetch("/printers");
    case "history":
      // v2.9.1 (audit L5 fix): clamp + integer the caller-provided limit
      return await hubFetch("/jobs?limit=" +
        Math.min(Math.max(parseInt(req.limit, 10) || 20, 1), 100));
    case "printPage": {
      const tab = (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
      const printer = req.destination === "file" ? "__file__"
        : (req.printer || (await resolvePrinter(tab.url || "", tab.title || req.title)));
      const out = await printPageDom(tab, req.title, printer);
      await flashBadge(true, "OK");
      return out;
    }
    case "printPdf": {
      const printer = req.destination === "file" ? "__file__"
        : (req.printer || (await resolvePrinter(req.url || "", req.title)));
      const out = await printPdfUrl(req.url, req.title, printer);
      await flashBadge(true, "OK");
      return out;
    }
    case "print": {
      // generic: {title, printer, copies, destination, priority, pages,
      //           profile, reason, watermark,
      //           pdfBase64 | pdfUrl | text | html | pageUrl}
      const o = req;
      const body = {
        title: o.title || "api",
        printer: o.printer || "",
        copies: o.copies || 1,
        source: "website"
      };
      if (o.destination === "file") { body.destination = "file"; body.printer = ""; }
      if (o.pdfBase64) body.pdf_base64 = o.pdfBase64;
      if (o.pdfUrl) body.pdf_url = o.pdfUrl;
      if (o.text != null) body.text = o.text;
      if (o.html != null) body.html = o.html;
      if (o.pageUrl) body.page_url = o.pageUrl;
      if (o.lang) body.lang = o.lang;                 // v2.0 raw: escpos|zpl
      if (o.rawBase64) body.raw_base64 = o.rawBase64; // v2.0 raw bytes
      if (o.priority) body.priority = o.priority;     // v2.0: 1 = urgent
      if (o.pages) body.pages = o.pages;              // v2.0: "1-3,5" | odd | even
      if (o.per_sheet) body.per_sheet = o.per_sheet;  // v2.1: n-up
      if (o.quality) body.quality = o.quality;        // v2.2: draft|normal|high|600dpi
      if (o.dpi) body.dpi = o.dpi;                    // v2.2: explicit DPI
      if (o.scale_pct) body.scale_pct = o.scale_pct;  // v2.1: 25-400
      if (o.margin_mm != null) body.margin_mm = o.margin_mm; // v2.1
      if (o.duplex) body.duplex = o.duplex;           // two-sided
      if (o.paper_size) body.paper_size = o.paper_size;
      if (o.orientation) body.orientation = o.orientation;
      if (o.profile) body.profile = o.profile;        // v2.0: hub profile name
      if (o.reason) body.reason = o.reason;           // v2.0: audit reason
      if (o.watermark != null) body.watermark = o.watermark;
      if (!body.pdf_base64 && !body.pdf_url && body.text == null &&
          body.html == null && !body.page_url && !body.raw_base64) {
        throw new HubError("advprint.print: provide pdfBase64, pdfUrl, text, html, pageUrl or rawBase64");
      }
      const out = await hubPrint(body);
      await rememberJob({ id: out.job_id, title: body.title,
                          printer: body.destination === "file" ? "File (PDF)" : "default",
                          status: out.status || "queued" });
      await flashBadge(true, "OK");
      return out;
    }
    default:
      throw new HubError("unknown api fn: " + req.fn);
  }
}

/* ---------------- context menus ---------------- */
async function rebuildMenus() {
  const cfg = await loadCfg();
  await chrome.contextMenus.removeAll();
  if (!cfg.contextMenu || cfg.enabled === false) return;   // no menu while disabled
  // v2.6.8: documentUrlPatterns - the menu only exists on pages that CAN
  // be printed (http/https/file). chrome://, edge://, chrome-extension://,
  // about: and the Web Store never show it again, so "Print this page"
  // can no longer fail with a permission error on the extension's own
  // options page.
  const DP = { documentUrlPatterns: ["http://*/*", "https://*/*",
                                     "file://*/*"] };
  chrome.contextMenus.create(Object.assign({
    id: "advprint-root", title: "AdvPrint Pro", contexts: ["all"]
  }, DP));
  chrome.contextMenus.create(Object.assign({
    id: "ph-print-page", parentId: "advprint-root",
    title: "Print this page", contexts: ["page"]
  }, DP));
  chrome.contextMenus.create(Object.assign({
    id: "ph-print-sel", parentId: "advprint-root",
    title: "Print selection", contexts: ["selection"]
  }, DP));
  chrome.contextMenus.create(Object.assign({
    id: "ph-print-link", parentId: "advprint-root",
    title: "Print linked PDF", contexts: ["link"]
  }, DP));
  chrome.contextMenus.create(Object.assign({
    id: "ph-shot", parentId: "advprint-root",
    title: "Print screenshot", contexts: ["page"]
  }, DP));
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if ((await loadCfg()).enabled === false) return;   // master switch OFF
    // v2.6.8: browser-internal pages (chrome://, edge://, extension
    // pages, Web Store) cannot be printed - friendly notice instead of
    // the old "must request permission to access this host" error
    if (!printableTab(tab) && info.menuItemId !== "ph-print-link") {
      notifyNotPrintable();
      return;
    }
    if (info.menuItemId === "ph-print-page" && tab) {
      await printTab(tab);
    } else if (info.menuItemId === "ph-print-sel" && info.selectionText) {
      await printSelection(info.selectionText, "selection");
    } else if (info.menuItemId === "ph-print-link" && info.linkUrl) {
      const printer = await resolvePrinter(info.linkUrl, "");
      await printPdfUrl(info.linkUrl, "link", printer);
    } else if (info.menuItemId === "ph-shot") {
      const win = await chrome.windows.getCurrent();
      await printScreenshot(win.id);
    }
  } catch (e) {
    await flashBadge(false, "!");
    reportDebug("error", "context menu print failed: " +
                String(e.message || e).slice(0, 300),
                info.menuItemId || "");
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/icon128.png",
      title: "AdvPrint Pro", message: String(e.message || e)
    });
  }
});

/* ---------------- toolbar command (Alt+P) ---------------- */
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "print-current-tab") return;
  if ((await loadCfg()).enabled === false) return;     // master switch OFF
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  try {
    if (!printableTab(tab)) { notifyNotPrintable(); return; }   // v2.6.8
    await printTab(tab);
  } catch (e) {
    await flashBadge(false, "!");
    reportDebug("error", "Alt+P print failed: " +
                String(e.message || e).slice(0, 300), tab.url || "");
    chrome.notifications.create({
      type: "basic", iconUrl: "icons/icon128.png",
      title: "AdvPrint Pro", message: String(e.message || e)
    });
  }
});

/* ---------------- v3.2.0: ONE UI central rule manager ----------------
 * The hub console (/ui Rules panel) edits rules_mirror on the hub; this
 * extension keeps itself in sync BOTH ways:
 *   - local rules changed (Options save / rule fired)  -> PUSH to the hub
 *     (with the live runs counter merged in from ruleStats)
 *   - alarm tick (every 5 min)                          -> PULL from the hub
 *     ADOPTED only when the local rules are unchanged since the last sync
 *     (local edits always win - no silent overwrite of user work).
 * The Website API whitelist (apiSites) is pushed too, so the ONE UI
 * Extension panel shows the live "*" / restricted list.
 * Every call targets the SELF PC hub (management lane, never the LAN/center
 * profile) and never throws - printing must not depend on bookkeeping. */
const HUB_SYNC_ALARM = "advprintHubSync";
let _rulesPushTimer = null;
let _adoptingHubRules = false;

function rulesHash(rules) {
  try { return btoa(unescape(encodeURIComponent(JSON.stringify(rules))))
    .slice(-32); } catch (_) { return ""; }
}

async function rulesWithRuns(rules) {
  const cfg = await loadCfg();
  let stats = {};
  try { stats = (await chrome.storage.local.get({ ruleStats: {} })).ruleStats
    || {}; } catch (_) {}
  return (rules || []).map((r) => {
    const s = stats[ruleKey(r)];
    return Object.assign({}, r,
      { runs: Math.max(r.runs || 0, (s && s.runs) || 0) });
  });
}

async function hubRulesSyncBase() {
  const cfg = await loadCfg();
  const base = (cfg.hubUrl || DEFAULTS.hubUrl).replace(/\/+$/, "");
  return { base, token: cfg.token || "" };
}

async function pushRulesToHub(rules, why) {
  try {
    const { base, token } = await hubRulesSyncBase();
    const payload = await rulesWithRuns(rules || []);
    await fetch(base + "/config", {
      method: "POST",
      headers: { "X-AdvPrint-Token": token,
                 "Content-Type": "application/json" },
      body: JSON.stringify({ rules_mirror: payload,
                             ext_sync_at: new Date().toISOString() }),
    });
    const st = await chrome.storage.local.get({ rulesSyncHash: "" });
    const h = rulesHash(payload);
    if (st.rulesSyncHash !== h) {
      await chrome.storage.local.set({ rulesSyncHash: h });
    }
  } catch (_) { /* hub may be offline - retried on the next alarm tick */ }
}

async function pushSitesToHub(sites) {
  try {
    const { base, token } = await hubRulesSyncBase();
    await fetch(base + "/config", {
      method: "POST",
      headers: { "X-AdvPrint-Token": token,
                 "Content-Type": "application/json" },
      body: JSON.stringify({ ext_api_sites: sites || ["*"] }),
    });
  } catch (_) { /* best effort */ }
}

async function pullRulesFromHub() {
  try {
    const { base, token } = await hubRulesSyncBase();
    const r = await fetch(base + "/config", {
      headers: { "X-AdvPrint-Token": token } });
    if (!r.ok) return;
    const cfgHub = await r.json();
    await adoptHubExtPrefs(cfgHub);          // v3.2.1 ONE UI power switches
    const mirror = Array.isArray(cfgHub.rules_mirror) ? cfgHub.rules_mirror
      : null;
    if (mirror === null) return;
    const st = await chrome.storage.local.get({ rulesSyncHash: "",
                                                rules: null });
    invalidateCfg();
    const localRules = st.rules || (await loadCfg()).rules || [];
    const mirrorHash = rulesHash(await rulesWithRuns(mirror));
    if (mirrorHash === st.rulesSyncHash) return;        // nothing new
    if (rulesHash(await rulesWithRuns(localRules)) === st.rulesSyncHash) {
      // local rules untouched since the last sync -> ADOPT hub rules
      _adoptingHubRules = true;
      try {
        await chrome.storage.local.set({
          rules: mirror.map((x) => Object.assign({}, x)),
          rulesSyncHash: mirrorHash });
      } finally { _adoptingHubRules = false; }
    } else {
      // local rules were edited - local WINS, push them back
      await pushRulesToHub(localRules, "local-wins");
    }
  } catch (_) { /* hub offline */ }
}

/* v3.2.1 ONE UI: the hub console's Power Switches / Browser Behavior /
   Printers "Default print options" panels are the MASTER of these keys.
   The hub stores them under ext_prefs using the SAME key names as this
   extension's storage, so adoption is 1:1. Applied on every hub sync
   (5-minute alarm + startup) - the ONE UI wins, exactly like rules. */
async function adoptHubExtPrefs(cfgHub) {
  const prefs = cfgHub && cfgHub.ext_prefs;
  if (!prefs || typeof prefs !== "object") return;
  const allowed = ["enabled", "queueMode", "rulesPaused", "hookPrint",
    "debugMode", "retryOffline", "lang", "autoPrintAllPdfs",
    "closeAfterPrint", "failFallback", "contextMenu", "badge"];
  const patch = {};
  let any = false;
  for (const k of allowed) {
    if (prefs[k] === undefined || prefs[k] === null) continue;
    patch[k] = prefs[k];
    any = true;
  }
  if (prefs.print_defaults && typeof prefs.print_defaults === "object" &&
      Object.keys(prefs.print_defaults).length) {
    patch.printDefaults = prefs.print_defaults;
    any = true;
  }
  if (!any) return;
  const cur = await chrome.storage.local.get(patch);
  const diff = Object.keys(patch).filter((k) => cur[k] !== patch[k]);
  if (!diff.length) return;
  _adoptingHubRules = true;         // suppress the push-back loop
  try {
    await chrome.storage.local.set(patch);
    invalidateCfg();
  } finally {
    _adoptingHubRules = false;
  }
}

function scheduleRulesPush(delayMs = 2500) {
  if (_rulesPushTimer) return;
  _rulesPushTimer = setTimeout(async () => {
    _rulesPushTimer = null;
    try {
      const st = await chrome.storage.local.get({ rules: null });
      invalidateCfg();
      const rules = st.rules || (await loadCfg()).rules || [];
      await pushRulesToHub(rules, "changed");
    } catch (_) {}
  }, delayMs);
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm && alarm.name === HUB_SYNC_ALARM) {
    pullRulesFromHub();            // v3.2.0 ONE UI central rule manager
  }
});
try { chrome.alarms.create(HUB_SYNC_ALARM, { periodInMinutes: 5 }); }
catch (_) {}                             // alarms API differences - ignore
chrome.runtime.onStartup.addListener(() => {
  try { chrome.alarms.create(HUB_SYNC_ALARM, { periodInMinutes: 5 }); }
  catch (_) {}
});

/* the ONE UI mirror: rules / whitelist edited anywhere are pushed */
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || _adoptingHubRules) return;
  if (changes.rules) { invalidateCfg(); scheduleRulesPush(); }
  if (changes.apiSites) { invalidateCfg();
    pushSitesToHub(changes.apiSites.newValue || ["*"]); }
});

/* ---------------- icon click = the POPUP (v3.2.4) ----------------
   v3.2.2 removed the popup; v3.2.4 brings it BACK by popular demand:
   the toolbar icon opens the quick popup again (master switches, queue,
   recent jobs + the Options button) while EVERY advanced option still
   lives in THE ONE UI console. The popup opens the console whenever
   deeper work is needed - one product, two depths.
   The onClicked listener below stays as a built-in fallback: it only
   fires if a future build ships without default_popup again. */
chrome.action.onClicked?.addListener?.(async () => {
  try {
    const st = await chrome.storage.local.get({ hubUrl: "", token: "" });
    let base = (st.hubUrl || "http://127.0.0.1:9235").replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(base)) base = "http://" + base;
    const url = base + "/ui" + (st.token ? "?token=" + encodeURIComponent(st.token) : "");
    chrome.tabs.create({ url });
  } catch (e) {
    chrome.tabs.create({ url: "http://127.0.0.1:9235/ui" });
  }
});

/* ---------------- lifecycle ---------------- */
chrome.runtime.onInstalled.addListener(async () => {
  const st = await chrome.storage.local.get({ initialized: false });
  if (!st.initialized) {
    // seed defaults once so Options shows the htncr.org example rule
    await chrome.storage.local.set(Object.assign({}, DEFAULTS, { initialized: true }));
  } else {
    // v2.9.1 -> v3.2.0: ONE-TIME migration for installs that predate the
    // Website API allowlist. From v3.2.0 the product default is "*"
    // (ALL websites may print - the ONE UI Rules panel shows the live
    // list); users who restrict it keep their list untouched.
    const cur = await chrome.storage.local.get({ apiSites: null });
    if (cur.apiSites === null) {
      await chrome.storage.local.set({ apiSites: ["*"] });
    }
  }
  await applyEnabledBadge();
  await updateRetryBadge();
  await flushRetries("installed");
  await verifyJobs();          // v2.2.1: resume checking submitted jobs
  await rebuildMenus();
  await applyHook();
});

chrome.runtime.onStartup.addListener(async () => {
  await applyEnabledBadge();
  await updateRetryBadge();
  await flushRetries("startup");
  await verifyJobs();          // v2.2.1: resume checking submitted jobs
  await rebuildMenus();
  await applyHook();
});

// MV3 service workers wake on events - make sure open tabs always have
// the hook (idempotent; cheap because of the __advprint* guards).
applyEnabledBadge();
injectIntoOpenTabs();
