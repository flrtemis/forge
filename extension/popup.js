/* FORGE — toolbar popup. */
"use strict";
const api = typeof browser !== "undefined" ? browser : chrome;

const DEFAULTS = { server: "http://127.0.0.1:5004", token: "", lang: "en", speed: 1.0 };

function $(id) { return document.getElementById(id); }

async function activeTab() {
  const tabs = await api.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

function tell(tabId, msg) {
  return api.tabs.sendMessage(tabId, msg).catch(() =>
    api.tabs.executeScript(tabId, { file: "player.js" })
      .then(() => api.tabs.sendMessage(tabId, msg))
  );
}

function withToken(url, token) {
  if (!token) return url;
  return url + (url.indexOf("?") > -1 ? "&" : "?") + "token=" + encodeURIComponent(token);
}

document.addEventListener("DOMContentLoaded", async () => {
  const s = await new Promise((r) => api.storage.local.get(DEFAULTS, r));
  $("speed").value = s.speed;
  $("speed-out").textContent = Number(s.speed).toFixed(2) + "×";

  // Which voice is loaded, and is the server up?
  try {
    const res = await fetch(withToken(s.server.replace(/\/+$/, "") + "/health", s.token));
    const j = await res.json();
    $("state").textContent = j.voice ? (j.name || j.voice) : "no voice set (start with --voice)";
    $("state").className = "pill ok";
    if (j.languages && j.languages.indexOf(s.lang) === -1 && j.languages.length) {
      s.lang = j.languages.indexOf("en") > -1 ? "en" : j.languages[0];
      await new Promise((r) => api.storage.local.set({ lang: s.lang }, r));
    }
    if (j.languages && j.languages.length) {
      $("lang").innerHTML = "";
      j.languages.forEach((l) => {
        const o = document.createElement("option");
        o.value = l; o.textContent = l;
        $("lang").appendChild(o);
      });
    }
  } catch (e) {
    $("state").textContent = "server offline — run python -m forge.server";
    $("state").className = "pill warn";
  }
  $("lang").value = s.lang;

  $("lang").addEventListener("change", () => api.storage.local.set({ lang: $("lang").value }));
  $("speed").addEventListener("input", () => {
    $("speed-out").textContent = Number($("speed").value).toFixed(2) + "×";
    api.storage.local.set({ speed: Number($("speed").value) });
  });

  $("selection").addEventListener("click", async () => {
    const tab = await activeTab();
    const sel = await api.tabs.executeScript(tab.id, {
      code: "window.getSelection().toString()"
    }).catch(() => [""]);
    const text = (sel && sel[0]) || "";
    await tell(tab.id, { forge: "speak", from: "selection", text, maxChars: 900 });
    window.close();
  });

  $("page").addEventListener("click", async () => {
    const tab = await activeTab();
    await tell(tab.id, { forge: "speak", from: "page", maxChars: 900 });
    window.close();
  });

  $("stop").addEventListener("click", async () => {
    const tab = await activeTab();
    await tell(tab.id, { forge: "stop" });
    window.close();
  });

  $("options").addEventListener("click", (e) => {
    e.preventDefault();
    api.runtime.openOptionsPage();
  });
});
