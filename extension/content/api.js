/* AdvPrint Pro - MAIN world developer API (v2.0).
 * Injected into every http(s) page by the browser itself (CSP-immune).
 *
 *   window.advprint.status()                 -> hub health
 *   window.advprint.printers()               -> [{name, is_default, status}]
 *   window.advprint.history(20)              -> last jobs
 *   window.advprint.printPage({title})       -> print current page
 *   window.advprint.printPdf(url, {title})   -> print a PDF URL (pure)
 *   window.advprint.print({                  -> generic hub print
 *     title, printer, copies, priority, pages, profile, reason,
 *     watermark, lang, rawBase64,
 *     pdfBase64 | pdfUrl | text | html | pageUrl
 *   })
 *   v2.0 extras:
 *     priority: 1 (urgent) .. 9 (low)        -> queue jump
 *     pages: "1-3,5"                          -> page range (PDF prints)
 *     profile: hub print-profile name         -> paper/tray/duplex preset
 *     lang: "escpos"|"zpl" + text             -> RAW receipt/label printing
 *     reason: "..."                           -> recorded in the audit log
 *   })
 *
 * GLOBAL one-liner with automatic browser fallback:
 *   printPdfLink(url, title, {timeout, fallback})
 *     1. silent: hub prints the PDF (session cookies, no tab, no dialog)
 *     2. hub/extension/hub-down failure -> window.open(url) so the browser
 *        default path still delivers the printout
 *   Also available as window.advprint.printPdfLink. Resolves with the hub
 *   job JSON on success, rejects after opening the fallback tab.
 *
 * Every method returns a Promise with the hub JSON response.
 * See docs/EXTENSION-API.md for full examples. */
(function () {
  if (window.advprint) return;
  let seq = 0;
  const pending = new Map();
  let failDefault = "tab";   // live from Options: "tab" | "none"

  window.addEventListener("message", (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d || d.__advprint !== true) return;
    if (d.kind === "state") {
      // relay broadcasts the Options state (also on live change)
      failDefault = d.failFallback === "none" ? "none" : "tab";
      return;
    }
    if (d.kind !== "api-resp") return;
    const p = pending.get(d.requestId);
    if (p) {
      pending.delete(d.requestId);
      p(d.response || { ok: false, error: "empty response" });
    }
  });

  function call(payload, timeoutMs) {
    return new Promise((resolve) => {
      const requestId = ++seq + "-" + Date.now();
      pending.set(requestId, resolve);
      window.postMessage({ __advprint: true, kind: "api", requestId, payload }, "*");
      setTimeout(() => {
        if (pending.has(requestId)) {
          pending.delete(requestId);
          resolve({
            ok: false,
            error: "AdvPrint timeout - is the extension connected and the hub running?"
          });
        }
      }, timeoutMs || 30000);
    });
  }

  /* printPdfLink - the short global: silent first, browser fallback second.
   * Fallback default comes from Options > "When a page print call fails"
   * (failFallback: "tab" opens the URL in a new tab, "none" stays silent).
   * A per-call opts.fallback (true/false) overrides the setting. */
  function printPdfLink(url, title, opts) {
    opts = opts || {};
    const wantFallback = opts.fallback !== undefined
      ? !!opts.fallback
      : failDefault !== "none";
    const openTab = () => {
      if (wantFallback) {
        try { window.open(url, "_blank"); } catch (_) {}
      }
    };
    if (!window.advprint || !window.advprint.printPdf) {
      openTab();
      return Promise.reject(new Error("AdvPrint Pro extension not loaded"));
    }
    return call({ fn: "printPdf", url: url, title: title || "PDF" }, opts.timeout).then(
      (r) => {
        if (r && r.ok !== false) return r;
        openTab();
        throw new Error((r && r.error) || "AdvPrint print failed");
      },
      (e) => {
        openTab();
        throw e;
      }
    );
  }

  /* v2.6.2 SINGLE VERSION SOURCE: the version comes from the DOM
   * attribute stamped by the ISOLATED-world relay (which reads the
   * real manifest). The string below is only a last-resort fallback. */
  var _apVerFallback = "3.1.2";
  function _apVersion() {
    try {
      var v = document.documentElement &&
              document.documentElement.getAttribute("data-advprint-ver");
      return v || _apVerFallback;
    } catch (_) {
      return _apVerFallback;
    }
  }

  window.advprint = {
    get version() { return _apVersion(); },
    status: () => call({ fn: "status" }),
    printers: () => call({ fn: "printers" }),
    history: (limit) => call({ fn: "history", limit: limit || 20 }),
    printPage: (opts) => call(Object.assign({ fn: "printPage" }, opts || {})),
    printPdf: (url, opts) =>
      call(Object.assign({ fn: "printPdf", url: url }, opts || {})),
    print: (opts) => call(Object.assign({ fn: "print" }, opts || {})),
    printPdfLink: printPdfLink
  };

  /* bare global so page code can simply call: printPdfLink(url, 'Title') */
  window.printPdfLink = printPdfLink;
})();
