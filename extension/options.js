/* AdvPrint Pro v3.2.1 - Options page = one-click opener for THE ONE UI.
   v3.2.0 carried a full standalone options UI here; since v3.2.1 every
   option lives inside the hub console at http://127.0.0.1:9235 (17 tabs).
   This page redirects straight to it and only falls back to a token
   field when the hub is not reachable. */
const HUB = "http://127.0.0.1:9235";

const st = document.getElementById("st");
const tokRow = document.getElementById("tokRow");

async function tryHub() {
  const tok = (await chrome.storage.local.get({ token: "" })).token;
  try {
    const r = await fetch(HUB + "/health", {
      headers: tok ? { "X-AdvPrint-Token": tok } : {},
    });
    if (r.ok) {
      st.textContent = "✓ Hub is running — opening THE ONE UI …";
      const url = HUB + "/?token=" + encodeURIComponent(tok || "");
      setTimeout(() => (location.href = url), 350);
      return true;
    }
  } catch (_) { /* hub offline */ }
  return false;
}

(async () => {
  if (await tryHub()) return;
  st.className = "st bad";
  st.innerHTML =
    "✖ Hub not reachable at " + HUB +
    " — start <b>AdvPrint Pro</b> (tray icon) first, then click again.";
  tokRow.style.display = "flex";
  document.getElementById("go").textContent = "Retry";
})();

document.getElementById("go").addEventListener("click", async () => {
  if (await tryHub()) return;
  st.className = "st bad";
  st.innerHTML = "✖ Still offline — start the AdvPrint Pro app (system tray), " +
    "then click Retry. The console opens in a normal browser tab.";
});

document.getElementById("save").addEventListener("click", async () => {
  const t = document.getElementById("tok").value.trim();
  if (!t) return;
  await chrome.storage.local.set({ token: t });
  st.className = "st";
  st.textContent = "Token saved — retrying …";
  if (await tryHub()) return;
  st.className = "st bad";
  st.innerHTML = "✖ Token saved, but the hub is still offline. Start the app and Retry.";
});
