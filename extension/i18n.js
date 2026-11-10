/* AdvPrint Pro v3.2.8 - UI language: English + Bangla (বাংলা).
 * Used by the popup, the options page and the notifications (the popup
 * is BACK in v3.2.5 with its branding-only footer; the toolbar icon
 * opens the popup, exactly like before v3.2.2).
 * The language comes from:
 *   1. chrome.storage.local.lang ("en" | "bn"), set in Options
 *   2. fallback: the browser UI language (auto-detect)
 * Usage in HTML: <span data-i18n="optLanguage">..</span>
 * In JS:         const s = await t("optLanguage");
 */
(function (global) {
  "use strict";
  const STRINGS = {
    en: {
      appName: "AdvPrint Pro",
      // popup
      popOffline: "Hub offline - jobs are saved and will retry",
      popRetryNow: "Retry now",
      popRetryCount: "job(s) waiting to retry",
      popTokenWarn: "You are using the DEFAULT token - change it in Options",
      popTokenBad: "The hub REJECTED your stored token - click Fix token (or update it in Options)",
      popTokenLocked: "Hub is rate-limiting this IP - retries paused, will resume automatically",
      popStatAuth: "Hub running - token mismatch (one click to fix)",
      popStatSlow: "Hub starting - wait a moment, then reopen",
      popStatSlowHint: "The hub process is up but its health check has not answered yet - the first start can be slow.",
      popFixTokenBtn: "Fix token",
      popFixTokenWorking: "Asking the hub for the current token...",
      popFixTokenOk: "Token fixed automatically - connected to the hub",
      popFixTokenFail: "Automatic fix did not work - paste the token in Options > Settings",
      popSwitchEnabled: "AdvPrint enabled",
      popEnabledOn: "printing is on",
      popEnabledOff: "printing is OFF - nothing prints",
      popSwitchQueue: "Queue mode",
      popQueueOn: "jobs wait in order + pause works",
      popQueueOff: "instant print - auto-queues if no printer is active",
      popPrinting: "Sending to printer...",
      popQueued: "Queued as job #",
      popSaved: "Saved as PDF",
      popCheckPrinter: " - check the printer",
      popFailed: "Failed: ",
      popHubOfflineHint: "Hub not reachable. Start it:  python advprint.py serve",
      popPaused: "PAUSED",
      popRunning: "running",
      popResume: "Resume",
      popPause: "Pause",
      popRecentJobs: "Recent jobs",
      popNoJobs: "No jobs yet - print something!",
      popEnabledMsg: "AdvPrint enabled",
      popDisabledMsg: "AdvPrint disabled - nothing will print",
      popQueueOnMsg: "Queue mode ON - jobs are printed in FIFO order",
      popQueueOffMsg: "Instant print ON - jobs print immediately; if no printer is active they are auto-queued for later",
      popLanSection: "LAN sharing",
      popPowerSection: "Power",
      popShareRx: "Share Receive Mode",
      popShareRxOn: "this PC accepts jobs from other PCs",
      popShareRxOff: "this PC prints only for itself",
      popShareRxMsgOn: "Share Receive Mode ON - RESTART the hub (tray icon → Exit, start again) so other PCs can connect. Check the firewall!",
      popShareRxMsgOff: "Share Receive Mode OFF - the hub only listens on this PC (restart it to unbind the LAN)",
      popShareTx: "Share Send Mode",
      popShareTxOn: "printing goes to the LAN PC",
      popShareTxOff: "printing on this PC",
      popShareTxOnLan: "printing goes to",
      popShareTxNoUrl: "Share Send needs a LAN PC first - Options > Connection 2 (LAN PC): URL + token",
      popShareTxMsgOn: "Share Send ON - print jobs go to the LAN PC (Connection 2 in Options)",
      popShareTxMsgOff: "Share Send OFF - print jobs stay on this PC",
      popShareRxOffline: "connect to the hub first",
      popTestQueued: "Test page queued as job #",
      popScreenshotQueued: "Screenshot queued as job #",
      popCapturing: "Capturing screenshot...",
      popSavingPdf: "Saving page as PDF file...",
      popConfigError: "Config error",
      // options
      optLanguage: "UI language",
      optLangAuto: "Automatic (browser language)",
      optRetryOffline: "Retry when the hub comes back",
      optRetryOfflineDesc: "If the hub is offline, jobs are kept in the browser and sent automatically as soon as the hub answers again (checked every minute).",
      optDashboard: "Open hub dashboard",
      optAudit: "Open audit log",
      optRulesRegex: "URL pattern (glob or regex)",
      optRulesTitle: "Page title contains",
      optRulesEnabled: "On",
      optRulesType: "Type",
      optTypeGlob: "Glob (* wildcard)",
      optTypeRegex: "Regex",
      // about / branding
      brandLine: "Version 3.2.8 - AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare Solutions - MIT license - 100% local - no cloud, no tracking."
    },
    bn: {
      appName: "AdvPrint Pro",
      popOffline: "হাব অফলাইন - কাজ সংরক্ষিত আছে, পরে আবার চেষ্টা হবে",
      popRetryNow: "এখন পুনরায় চেষ্টা করুন",
      popRetryCount: "টি কাজ পুনরায় পাঠানোর অপেক্ষায়",
      popTokenWarn: "আপনি ডিফল্ট টোকেন ব্যবহার করছেন - Options থেকে বদলান",
      popTokenBad: "হাব আপনার সংরক্ষিত টোকেন প্রত্যাখ্যান করেছে - Fix token চাপুন (বা Options থেকে টোকেন দিন)",
      popTokenLocked: "হাব এই IP সাময়িকভাবে সীমিত করেছে - রিট্রি বিরতিতে আছে, স্বয়ংক্রিয়ভাবে পুনরায় শুরু হবে",
      popStatAuth: "হাব চালু আছে - টোকেন মিলছে না (এক ক্লিকে ঠিক হবে)",
      popStatSlow: "হাব চালু হচ্ছে - একটু অপেক্ষা করে আবার খুলুন",
      popStatSlowHint: "হাব প্রসেস চালু আছে কিন্তু হেলথ চেক এখনো উত্তর দেয়নি - প্রথম শুরু ধীর হতে পারে।",
      popFixTokenBtn: "টোকেন ঠিক করুন",
      popFixTokenWorking: "হাব থেকে বর্তমান টোকেন আনা হচ্ছে...",
      popFixTokenOk: "টোকেন স্বয়ংক্রিয়ভাবে ঠিক হয়েছে - হাবের সাথে সংযোগ হয়েছে",
      popFixTokenFail: "স্বয়ংক্রিয় ঠিক করা যায়নি - Options > Settings থেকে টোকেন দিন",
      popSwitchEnabled: "অ্যাডভান্সড প্রিন্টার চালু",
      popEnabledOn: "প্রিন্টিং চালু আছে",
      popEnabledOff: "প্রিন্টিং বন্ধ - কিছুই প্রিন্ট হবে না",
      popSwitchQueue: "কিউ মোড",
      popQueueOn: "কাজ লাইনে অপেক্ষা করে + পজ কাজ করে",
      popQueueOff: "ইনস্ট্যান্ট প্রিন্ট - প্রিন্টার সক্রিয় না থাকলে স্বয়ংক্রিয়ভাবে কিউ হয়",
      popPrinting: "প্রিন্টারে পাঠানো হচ্ছে...",
      popQueued: "কিউ হয়েছে, জব #",
      popSaved: "PDF হিসেবে সংরক্ষিত",
      popCheckPrinter: " - প্রিন্টার দেখুন",
      popFailed: "ব্যর্থ: ",
      popHubOfflineHint: "হাব পাওয়া যাচ্ছে না। চালু করুন:  python advprint.py serve",
      popPaused: "বিরত",
      popRunning: "চলছে",
      popResume: "চালু করুন",
      popPause: "বিরত করুন",
      popRecentJobs: "সাম্প্রতিক কাজ",
      popNoJobs: "এখনও কোনো কাজ নেই - কিছু প্রিন্ট করুন!",
      popEnabledMsg: "অ্যাডভান্সড প্রিন্টার চালু হয়েছে",
      popDisabledMsg: "অ্যাডভান্সড প্রিন্টার বন্ধ - কিছুই প্রিন্ট হবে না",
      popQueueOnMsg: "কিউ মোড চালু - কাজ ক্রমানুসারে প্রিন্ট হবে",
      popQueueOffMsg: "কিউ মোড বন্ধ - কাজ সাথে সাথে প্রিন্ট হবে",
      popLanSection: "LAN শেয়ারিং",
      popPowerSection: "পাওয়ার",
      popShareRx: "শেয়ার রিসিভ মোড",
      popShareRxOn: "এই পিসি অন্য পিসি থেকে কাজ নেয়",
      popShareRxOff: "এই পিসি শুধু নিজের জন্য প্রিন্ট করে",
      popShareRxMsgOn: "শেয়ার রিসিভ মোড চালু - অন্য পিসি সংযোগ পেতে হাব রিস্টার্ট করুন (ট্রে আইকন → Exit, আবার চালু)। ফায়ারওয়াল দেখুন!",
      popShareRxMsgOff: "শেয়ার রিসিভ মোড বন্ধ - হাব শুধু এই পিসিতে শোনে (LAN আনবাইন্ড করতে রিস্টার্ট করুন)",
      popShareTx: "শেয়ার সেন্ড মোড",
      popShareTxOn: "প্রিন্ট LAN পিসিতে যাবে",
      popShareTxOff: "এই পিসিতে প্রিন্ট হবে",
      popShareTxOnLan: "প্রিন্ট যাবে",
      popShareTxNoUrl: "শেয়ার সেন্ডের আগে LAN পিসি দরকার - Options > Connection 2 (LAN PC): URL + টোকেন",
      popShareTxMsgOn: "শেয়ার সেন্ড চালু - প্রিন্ট কাজ LAN পিসিতে যাবে (Options-এ Connection 2)",
      popShareTxMsgOff: "শেয়ার সেন্ড বন্ধ - প্রিন্ট কাজ এই পিসিতেই হবে",
      popShareRxOffline: "আগে হাবের সাথে সংযোগ করুন",
      popTestQueued: "টেস্ট পেজ কিউ হয়েছে, জব #",
      popScreenshotQueued: "স্ক্রিনশট কিউ হয়েছে, জব #",
      popCapturing: "স্ক্রিনশট নেওয়া হচ্ছে...",
      popSavingPdf: "পেজ PDF হিসেবে সংরক্ষিত হচ্ছে...",
      popConfigError: "কনফিগ সমস্যা",
      optLanguage: "ইন্টারফেস ভাষা",
      optLangAuto: "স্বয়ংক্রিয় (ব্রাউজারের ভাষা)",
      optRetryOffline: "হাব ফিরে এলে আবার পাঠান",
      optRetryOfflineDesc: "হাব অফলাইন থাকলে কাজগুলো ব্রাউজারে জমা থাকে এবং হাব চালু হতেই স্বয়ংক্রিয়ভাবে পাঠানো হয় (প্রতি মিনিটে পরীক্ষা)।",
      optDashboard: "হাব ড্যাশবোর্ড খুলুন",
      optAudit: "অডিট লগ খুলুন",
      optRulesRegex: "URL প্যাটার্ন (glob বা regex)",
      optRulesTitle: "পেজ শিরোনামে থাকবে",
      optRulesEnabled: "চালু",
      optRulesType: "ধরন",
      optTypeGlob: "Glob (* ওয়াইল্ডকার্ড)",
      optTypeRegex: "Regex",
      brandLine: "সংস্করণ 3.2.8 - AdvPrint Pro (Advanced Printer) by Bit Dream IT - Innovative Healthcare Solutions - MIT লাইসেন্স - ১০০% লোকাল - কোনো ক্লাউড নেই, কোনো ট্র্যাকিং নেই।"
    }
  };

  function detect() {
    try {
      const ui = (chrome.i18n && chrome.i18n.getUILanguage ?
                  chrome.i18n.getUILanguage() : "en").toLowerCase();
      return ui.startsWith("bn") ? "bn" : "en";
    } catch (_) { return "en"; }
  }

  function dict(lang) {
    return STRINGS[lang] || STRINGS[detect()];
  }

  function t(key, lang) {
    const d = dict(lang);
    return d[key] != null ? d[key] : (STRINGS.en[key] || key);
  }

  function apply(lang) {
    const d = dict(lang);
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const v = d[el.dataset.i18n];
      if (v != null) el.textContent = v;
    });
    document.querySelectorAll("[data-i18n-ph]").forEach((el) => {
      const v = d[el.dataset.i18nPh];
      if (v != null) el.placeholder = v;
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const v = d[el.dataset.i18nTitle];
      if (v != null) el.title = v;
    });
  }

  async function currentLang() {
    try {
      const st = await chrome.storage.local.get({ lang: "auto" });
      return st.lang === "auto" ? detect() : st.lang;
    } catch (_) { return detect(); }
  }

  global.AdvPrintI18n = { t, apply, detect, currentLang, languages: Object.keys(STRINGS) };
})(typeof window !== "undefined" ? window : this);
