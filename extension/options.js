/* AdvPrint Pro v3.2.4 - Options page = BRANDING ONLY.
   Since v3.2.1 (and fully from v3.2.2) EVERY option lives inside the hub
   console (THE ONE UI) at http://127.0.0.1:9235 - there are no
   Console/Dashboard/Debug buttons here anymore, just the brand card.
   The card opens the console: automatically when the hub answers, and on
   click. A token field appears ONLY when the hub refuses the saved token. */
const HUB = "http://127.0.0.1:9235";

const st = document.getElementById("st");
const tokRow = document.getElementById("tokRow");

async function tryOpen() {
  const tok = (await chrome.storage.local.get({ token: "" })).token;
  try {
    const r = await fetch(HUB + "/health", {
      headers: tok ? { "X-AdvPrint-Token": tok } : {},
    });
    if (r.ok) {
      st.className = "st";
      st.textContent = "Hub is running \u2014 opening THE ONE UI console \u2026";
      const url = HUB + "/?token=" + encodeURIComponent(tok || "");
      setTimeout(() => (location.href = url), 300);
      return true;
    }
    if (r.status === 401) {
      st.className = "st bad";
      st.textContent = "Hub needs the token once \u2014 paste it below to continue.";
      tokRow.style.display = "flex";
      return true;
    }
  } catch (_) { /* hub offline */ }
  return false;
}

function offline() {
  st.className = "st bad";
  st.innerHTML =
    "Hub not reachable \u2014 start <b>AdvPrint Pro</b> (system tray icon), " +
    "then click this card again.";
}

(async () => {
  if (!(await tryOpen())) offline();
})();

document.getElementById("brand").addEventListener("click", async (e) => {
  if (e.target && (e.target.id === "save" || e.target.id === "tok")) return;
  if (await tryOpen()) return;
  offline();
});

document.getElementById("save").addEventListener("click", async () => {
  const t = document.getElementById("tok").value.trim();
  if (!t) return;
  await chrome.storage.local.set({ token: t });
  st.className = "st";
  st.textContent = "Token saved \u2014 opening the console \u2026";
  tokRow.style.display = "none";
  if (!(await tryOpen())) offline();
});
