"use strict";
/* tests/ext_sync_sim.js - v3.5.10 ONE POWER SWITCH behavioral test.
 *
 * Executes the REAL extension/background.js inside a simulated chrome
 * service-worker environment with an in-memory hub, then replays the
 * EXACT owner-reported scenario:
 *
 *   1. popup flips the master switch OFF      -> hub must LEARN it
 *      (pushExtPrefsToHub POSTs the full ext_prefs object, preserving
 *      print_defaults - the v3.5.9-and-before bug: the hub never
 *      learned, and its stale copy reverted the flip 5 min later)
 *   2. popup flips with the hub OFFLINE       -> change stays PENDING
 *   3. the STALE hub copy arrives (the old 5-min alarm)  -> adoption
 *      must be SKIPPED while a local push is pending (no auto-revert)
 *   4. hub comes back, extPrefSyncTick() runs -> pending push lands
 *   5. the CONSOLE flips the switch back ON   -> last writer wins,
 *      the browser follows (adoption works again)
 *   6. console flips a key the popup never touched -> getCfg (popup
 *      open) adopts it at once
 *
 * Prints ONE JSON object on stdout: {"pass":bool,"checks":{...}}.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const BG = fs.readFileSync(path.join(ROOT, "extension", "background.js"),
                           "utf-8");

/* ---------------- in-memory hub ---------------- */
const HUB_CFG = {
  ext_prefs: { enabled: true, queueMode: true,
               print_defaults: { copies: 2 } },
};
let FAIL_POST = false;

function hubFetch(url, opts) {
  const u = new URL(url);
  const method = ((opts && opts.method) || "GET").toUpperCase();
  if (u.pathname === "/config") {
    if (method === "GET") {
      return Promise.resolve({ ok: true, status: 200,
        json: async () => JSON.parse(JSON.stringify(HUB_CFG)) });
    }
    if (FAIL_POST) return Promise.reject(new Error("hub offline"));
    const body = JSON.parse(opts.body);
    Object.assign(HUB_CFG, body);
    return Promise.resolve({ ok: true, status: 200,
      json: async () => ({ ok: true }) });
  }
  return Promise.resolve({ ok: true, status: 200,
    json: async () => ({}) });
}

/* ---------------- chrome stub ---------------- */
const storageData = {};                    // chrome.storage.local mirror
let onChangedListeners = [];
const alarmsCreated = {};
let alarmHandler = null;
let messageHandler = null;

const storageLocal = {
  async get(arg) {
    if (arg === null || arg === undefined) return Object.assign({}, storageData);
    if (typeof arg === "string") return { [arg]: storageData[arg] };
    if (Array.isArray(arg)) {
      const out = {};
      for (const k of arg) out[k] = storageData[k];
      return out;
    }
    const out = {};                        // object = defaults
    for (const k of Object.keys(arg)) {
      out[k] = storageData[k] !== undefined ? storageData[k] : arg[k];
    }
    return out;
  },
  async set(obj) {
    const changes = {};
    for (const k of Object.keys(obj)) {
      const old = storageData[k];
      storageData[k] = obj[k];
      changes[k] = { oldValue: old, newValue: obj[k] };
    }
    for (const l of [...onChangedListeners]) l(changes, "local");
  },
  async remove(keys) {
    for (const k of (Array.isArray(keys) ? keys : [keys])) delete storageData[k];
  },
};

function anyStub() {
  const t = function noop() { return Promise.resolve(); };
  return new Proxy(t, {
    get(tt, p) {
      if (p === "then" || p === Symbol.toPrimitive) return undefined;
      if (!(p in tt)) tt[p] = anyStub();
      return tt[p];
    },
    apply() { return Promise.resolve(); },
  });
}

const chromeBase = {
  storage: {
    local: storageLocal,
    session: { async get() { return {}; }, async set() {},
               setAccessLevel: async () => {} },
    managed: { async get() { return {}; } },
    onChanged: { addListener: (f) => onChangedListeners.push(f) },
  },
  alarms: {
    create: (n, info) => { alarmsCreated[n] = info; },
    clear: async () => {},
    onAlarm: { addListener: (f) => { alarmHandler = f; } },
  },
  runtime: {
    onStartup: { addListener: (f) => {} },
    onInstalled: { addListener: (f) => {} },
    onMessage: { addListener: (f) => { messageHandler = f; } },
    getManifest: () => ({ version: "3.5.10" }),
  },
  commands: { onCommand: { addListener: (f) => {} } },
  action: { setBadgeText: async () => {}, setBadgeBackgroundColor: async () => {},
            onClicked: { addListener: () => {} } },
  tabs: { query: async () => [], create: async () => {}, remove: async () => {},
          get: async () => ({}), onUpdated: { addListener: () => {} },
          captureVisibleTab: async () => "" },
  contextMenus: { create: () => {}, removeAll: () => {},
                  onClicked: { addListener: () => {} } },
  notifications: { create: async () => {} },
  scripting: { executeScript: async () => [],
               registerContentScripts: () => {},
               unregisterContentScripts: () => {},
               getRegisteredContentScripts: async () => [] },
  windows: { getCurrent: async () => ({ id: 1 }) },
};

const chromeProxy = new Proxy(chromeBase, {
  get(t, p) {
    if (p in t) return t[p];
    t[p] = anyStub();
    return t[p];
  },
});

/* ---------------- run the REAL background.js ---------------- */
const sandbox = {
  chrome: chromeProxy,
  fetch: hubFetch,
  console: { log: () => {}, warn: () => {}, error: () => {} },
  setTimeout, clearTimeout, setInterval, clearInterval,
  URL, URLSearchParams, Date, JSON, Math, Object, Array, Promise, Error,
  TypeError, Number, String, Boolean, RegExp, Map, Set, Symbol, Proxy,
  Uint8Array, Int32Array, ArrayBuffer, DataView, TextEncoder, TextDecoder,
  btoa: (s) => Buffer.from(s, "binary").toString("base64"),
  atob: (s) => Buffer.from(s, "base64").toString("binary"),
  escape, unescape,
  self: { addEventListener: () => {} },
  crypto: { getRandomValues: (a) => a },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(BG, sandbox, { filename: "background.js" });

const run = (code) => vm.runInContext(code, sandbox, { filename: "probe.js" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const replies = [];

(async () => {
  const checks = {};
  try {
    /* the sync alarms must be registered (1-minute ext-pref sync) */
    checks.alarms =
      (alarmsCreated["advprintExtPrefSync"] || {}).periodInMinutes === 1 &&
      (alarmsCreated["advprintHubSync"] || {}).periodInMinutes === 5;

    /* 1. the popup flips the master switch OFF (the owner's exact step) */
    await storageLocal.set({ enabled: false });
    await sleep(1300);                       // 800 ms debounce + POST
    checks.popupOffReachesHub = HUB_CFG.ext_prefs.enabled === false;
    checks.printDefaultsPreserved =
      HUB_CFG.ext_prefs.print_defaults &&
      HUB_CFG.ext_prefs.print_defaults.copies === 2;
    checks.hubKeysMerged =
      HUB_CFG.ext_prefs.queueMode === true;  // console-owned key survives

    /* 2. popup flips the Queue switch with the hub OFFLINE */
    FAIL_POST = true;
    await storageLocal.set({ queueMode: false });
    await sleep(1300);
    checks.offlineFlipStaysLocal =
      storageData.queueMode === false && HUB_CFG.ext_prefs.queueMode === true;

    /* 3. the STALE hub copy arrives (the old 5-min alarm path) -
     *    adoption MUST be skipped while the push is pending */
    await run("adoptHubExtPrefs({ ext_prefs: { enabled: true, queueMode: true } })");
    await sleep(100);
    checks.noAutoRevertWhilePending =
      storageData.enabled === false && storageData.queueMode === false;

    /* 4. hub answers again - the 1-minute sync tick lands the push */
    FAIL_POST = false;
    await run("extPrefSyncTick()");
    await sleep(300);
    checks.pendingPushLands =
      HUB_CFG.ext_prefs.enabled === false &&
      HUB_CFG.ext_prefs.queueMode === false;
    checks.pendingFlagCleared =
      run("(_extPrefPushPending === false)") === true;

    /* 5. the CONSOLE flips the master switch back ON - last writer
     *    wins, the browser follows (adoption works again) */
    await run("adoptHubExtPrefs({ ext_prefs: { enabled: true } })");
    await sleep(100);
    checks.consoleFlipFollows = storageData.enabled === true;

    /* 6. console flips a key the popup never touched -> opening the
     *    popup (getCfg) adopts it at once */
    HUB_CFG.ext_prefs.hookPrint = false;
    messageHandler({ type: "getCfg" }, {}, (r) => replies.push(r));
    await sleep(400);
    checks.getCfgSyncsExtPrefs = storageData.hookPrint === false;
    checks.getCfgReplies = replies.length > 0 && replies[0].ok === true;

    /* the alarm must be wired to the tick */
    checks.alarmWired = typeof alarmHandler === "function";
  } catch (e) {
    checks.error = String(e && e.stack || e);
  }
  const pass = Object.keys(checks).every((k) => k === "error" ? false : checks[k]);
  process.stdout.write(JSON.stringify({ pass, checks }) + "\n");
  process.exit(pass ? 0 : 1);
})();
