/* FORGE — Firefox background script.
 * The toolbar button and the right-click menu both just tell the content
 * script in the active tab to read something. All playback lives in the page
 * (player.js) so it survives focus changes and the address bar closing. */
"use strict";

const api = typeof browser !== "undefined" ? browser : chrome;

const PARAGRAPH = 900;   // chars per request; the server caps at 5000

function tell(tabId, msg) {
  return api.tabs.sendMessage(tabId, msg).catch((e) => {
    // No content script yet (e.g. the tab was open before install) — inject
    // player.js once, then retry. activeTab covers this click.
    return api.tabs.executeScript(tabId, { file: "player.js" })
      .then(() => api.tabs.sendMessage(tabId, msg))
      .catch((err) => {
        console.error("[FORGE] cannot reach page:", err);
      });
  });
}

async function activeTab() {
  const tabs = await api.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

function buildMenus() {
  // Rebuilt on every event-page wake so a restart never leaves stale entries
  // (and never throws "duplicate menu id").
  api.menus.removeAll().then(() => {
    api.menus.create({
      id: "forge-read-selection",
      title: "FORGE: read the selection in my voice",
      contexts: ["selection"],
      documentUrlPatterns: ["<all_urls>"]
    });
    api.menus.create({
      id: "forge-read-page",
      title: "FORGE: read this page in my voice",
      contexts: ["page", "selection"],
      documentUrlPatterns: ["<all_urls>"]
    });
    api.menus.create({
      id: "forge-stop",
      title: "FORGE: stop reading",
      contexts: ["page", "selection"],
      documentUrlPatterns: ["<all_urls>"]
    });
  });
}

buildMenus();
api.runtime.onInstalled.addListener(buildMenus);
api.runtime.onStartup.addListener(buildMenus);

api.menus.onClicked.addListener(async (info, tab) => {
  if (!tab || !tab.id) return;
  if (info.menuItemId === "forge-read-selection") {
    tell(tab.id, { forge: "speak", text: info.selectionText || "", from: "selection", maxChars: PARAGRAPH });
  } else if (info.menuItemId === "forge-read-page") {
    tell(tab.id, { forge: "speak", from: info.selectionText ? "selection" : "page", maxChars: PARAGRAPH });
  } else if (info.menuItemId === "forge-stop") {
    tell(tab.id, { forge: "stop" });
  }
});

// (The toolbar button opens popup.html, so no browserAction.onClicked here.)

api.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || msg.forge !== "from-page") return;
  if (msg.what === "status") {
    api.browserAction.setBadgeText({ text: msg.badge || "" });
    api.browserAction.setBadgeBackgroundColor({ color: msg.error ? "#c0392b" : "#e8b04b" });
  }
});
