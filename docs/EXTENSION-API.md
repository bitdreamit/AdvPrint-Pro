# AdvPrint Pro — Browser / Extension API

## 0. The global one-liner: `printPdfLink(url, title)`

Since v1.1.6 the extension injects a bare global helper into **every** http(s) page (MAIN world, browser-initiated, immune to page CSP — works even with "Intercept window.print()" turned off). Silent first, browser fallback second:

```js
printPdfLink(url, title?, { timeout?, fallback? })
```

1. **SILENT** — the hub fetches the PDF with your login cookies and prints it. No tab, no dialog, paper just comes out. Resolves with the hub job JSON (`{ok:true, job_id:…}`).
2. **FALLBACK** — hub down / printer error / extension missing → the URL is opened in a normal tab so the browser's default print path still delivers. Then it **rejects** with the reason (so your `.catch()` can log it).

Typical page code — nothing to define, nothing to import:

```html
<button id="print_selected_btn">Print</button>
<script>
function doSilentPrint() {
  var form   = document.getElementById('print_form');
  var params = new URLSearchParams(new FormData(form)).toString();
  printPdfLink(form.action + '?' + params + '&_=' + Date.now(), 'Lab report');
}
document.getElementById('print_selected_btn')
        .addEventListener('click', doSilentPrint);
</script>
```

Guarded variant (safe even on machines without the extension):

```js
(window.printPdfLink || function (u, t) { window.open(u, '_blank'); })(url, 'Lab report');
// namespaced twin: window.advprint.printPdfLink(url, title)
```

**Fallback default is an extension setting** — Options > Behavior > **"When a page print call fails"** (`failFallback`): `tab` = open the URL in a new tab (browser fallback, default), `none` = stay completely silent (nothing opens, failure only logged). Changes apply live, no reload.

Options: `timeout` — ms to wait for the hub before falling back (default 30000); `fallback: true/false` — per-call override of the setting above. Note: if the extension is not installed the bare global does not exist, so use the guarded variant for public pages.

**No-tab mode** — pass `{ fallback: false }` to stay 100% silent: on failure the
promise just rejects (check the extension badge / job history), no tab is opened:

```js
printPdfLink(url, 'Lab report', { fallback: false })
  .catch(function (e) { alert('Print failed: ' + (e.message || e)); });
```

**No double paper** — v1.1.7 feeds every successful print (button, auto rule,
hook) into one shared 60-second dedupe, so a fallback-opened tab will never
print the same URL again. Keep auto rules pointed at **PDF endpoints only**
(e.g. `*://host/lab/medical_reports/pdf/*`) — a rule matching your HTML pages
makes every page open attempt a DOM render, which fails on login-protected
sites ("html render failed ... login required").

## 1. `window.advprint` (developer API, on every page)

Available on every http(s) page once the extension is loaded (v1.1.6 no longer requires "Intercept window.print()" — the API and `printPdfLink` are always injected). Every method returns a **Promise** with the hub JSON:

```js
await window.advprint.status();
// {ok:true, app:"AdvPrint Pro", version:"1.0.0", default_printer:"HP LaserJet Pro", ...}

await window.advprint.printers();
// {ok:true, printers:[{name:"XP-80C Thermal", is_default:false}, ...]}

await window.advprint.history(20);
// {ok:true, jobs:[{id, created_at, title, printer, kind, status}, ...]}

await window.advprint.printPage({ title: "Invoice 42", printer: "" });
// prints the current page (rendered to PDF by the hub)

await window.advprint.printPage({ title: "Archive copy", destination: "file" });
// saves the current page as a PDF file (default ~/Downloads/AdvPrint) - no paper

await window.advprint.printPdf("https://www.htncr.org/lab/medical_reports/pdf-test/…/605310",
                               { title: "Report 605310" });
// downloads with login cookies, prints silently

await window.advprint.print({
  title: "Receipt 12",
  printer: "XP-80C Thermal",   // omit for default
  copies: 1,
  text: "|center|MY SHOP\nItem 1   10.00\nTOTAL     10.00"
  // or: html: "<h1>Invoice</h1>"
  // or: pdfBase64: "JVBERi0..."
  // or: pdfUrl:  "https://…/report.pdf"
  // destination: "file"        // save as PDF instead of printing
});
```

**POS / kiosk example** — auto-print the current order after checkout:

```js
document.querySelector("#checkout").addEventListener("click", async () => {
  const r = await window.advprint.print({
    title: "Order " + order.id,
    text: "|center|MY SHOP\n" + order.lines.join("\n") + "\nTOTAL " + order.total,
  });
  if (!r.ok) console.warn("print failed:", r.error);
});
```

## 2. Silent printing triggers

| Trigger | How |
|---|---|
| **Any PDF opened in the browser** (simple mode, default ON) | Open any PDF - any site - and it prints silently, tab auto-closes. Toggle: Options > "Print every PDF opened in the browser". No rules needed. |
| Auto-print on URL open | Routing rule with **Auto** checked (first match wins). The tab is closed right after the print unless "Close tab after auto-print" is turned off in Options. |
| Print a PDF from page JS with no tab at all | `printPdfLink(url, 'Title')` — silent + automatic browser fallback; or `await window.advprint.printPdf(url)` — fetched with your login session, printed silently |
| Right-click menu | AdvPrint Pro → Print this page / selection / linked PDF / screenshot |
| Popup button | "Print this page", "Save as PDF", "Print screenshot", "Test page" |
| Keyboard | **Alt+P** prints the current tab |
| `window.print()` + Ctrl+P interception | Any web app calling `window.print()` — or the user pressing Ctrl+P / Cmd+P — is printed via the hub instead of the dialog. Browser-level injection, immune to page CSP. |
| Developer API | `window.advprint.*` (above) or direct HTTP |

## 3. Routing rules

Rules live in extension Options and in `chrome.storage.local` under key `rules`:

```json
[
  { "pattern": "*://www.htncr.org/lab/medical_reports/*",
    "printer": "",
    "action": "auto",     // auto = PDF if the URL serves a PDF, else page render
    "auto": true },       // print automatically when opened
  { "pattern": "*://erp.mycompany.com/orders/*",
    "printer": "XP-80C Thermal",
    "action": "page",
    "auto": false }
]
```

Pattern syntax: shell-style globs where `*` matches anything (`*://host/path/*`). HTTPS enforcement is yours to write into the pattern.

**File destination in rules:** set `"printer": "__file__"` (or pick **File (save as PDF)** in the Options dropdown) and matching jobs are saved as PDF files in the hub's file folder instead of printed — perfect for archiving every opened report automatically.

## 4. Enterprise deployment (GPO / MDM)

The extension reads Chrome **managed storage** (`chrome.storage.managed`, schema in `extension/managed.json`). IT admins can pre-provision and lock values via registry keys / MDM:

```
Windows registry:
HKLM\Software\Policies\Google\Chrome\ExtensionInstallForcelist   → force-install the extension
HKLM\Software\Policies\Google\Chrome\3rdparty\extensions\<EXT-ID>\policy\
    hubUrl          (REG_SZ)  e.g. http://127.0.0.1:9235
    token           (REG_SZ)
    defaultPrinter  (REG_SZ)
    rules           (JSON string)
```

Managed values override local user settings; managed `rules` fully replace user-defined rules.

## 4b. Popup switches + history manager (v2.7.0)

The popup now carries two LAN switches and Options > History got bulk
actions. New background message types (same `chrome.runtime.sendMessage`
protocol as before):

| Message | Effect |
|---|---|
| `{type:"jobBulkReprint", ids:[...]}` | POST /jobs/bulk-reprint with the given ids |
| `{type:"jobBulkReprint", scope:"not_printed"}` | Reprint every failed/dead/canceled job |
| `{type:"historyClear"}` | POST /history/clear (finished jobs only) |
| `{type:"saveCfg", patch:{lanSend:false}}` | **Share Send Mode OFF** — the background then refuses every `queueShift` |

`queueShift` respects the new **Share Send Mode**: when the popup switch
is OFF it answers
`{ok:false,error:"Share Send Mode is OFF - ..."}` and nothing is sent to
the peer PC. **Share Receive Mode** is hub-side (`share_lan` via
`hubConfigSet`) — a hub restart applies the listener change.

## 5. Direct HTTP from any web app

The hub API is CORS + Private-Network friendly, so page JS can call it directly (no extension needed):

```js
await fetch("http://127.0.0.1:9235/print", {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-AdvPrint-Token": "YOUR-TOKEN" },
  body: JSON.stringify({ text: "|center|HELLO", paper: "thermal" })
});
```

Prefer `window.advprint` in normal pages — it never exposes the token in page code.
