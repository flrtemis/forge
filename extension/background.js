/* FORGE — Firefox background script.
 * The toolbar button and the right-click menu both just tell the content
 * script in the active tab to read something. All playback lives in the page
 * (player.js) so it survives focus changes and the address bar closing. */
"use strict";

const api = typeof browser !== "undefined" ? browser : chrome;

const PARAGRAPH = 900;   // chars per request; the server caps at 5000

async function tell(tabId, msg) {
  try {
    await api.tabs.sendMessage(tabId, msg);
  } catch (e) {
    // No player in this tab yet (opened before the add-on was loaded) —
    // inject it once, then retry. The click's activeTab permission covers it.
    try {
      await api.tabs.executeScript(tabId, { file: "player.js" });
      await api.tabs.sendMessage(tabId, msg);
    } catch (err) {
      // about:, addons.mozilla.org, the PDF viewer and view-source: refuse
      // content scripts by design. Say so instead of failing silently.
      api.browserAction.setBadgeText({ text: "!" });
      api.browserAction.setBadgeBackgroundColor({ color: "#c0392b" });
      console.error(
        "[FORGE] Cannot read this page (" + (err && err.message) + ").\n" +
        "Firefox blocks extensions on about:, addons.mozilla.org, the built-in " +
        "PDF viewer, and view-source: pages. Copy the text instead and paste it " +
        "into http://127.0.0.1:5004/reader, or install a PDF/text viewer page.");
    }
  }
}

async function activeTab() {
  const tabs = await api.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

function buildMenus() {
  // The background page is persistent, so this runs once per browser session;
  // onInstalled re-runs it after an update (removeAll avoids duplicate ids).
  api.menus.removeAll().then(() => {
    api.menus.create({
      id: "forge-read-selection",
      title: "Read Aloud",
      contexts: ["selection"],
      documentUrlPatterns: ["<all_urls>"]
    });
    api.menus.create({
      id: "forge-read-page",
      title: "Read Aloud \u2014 whole page",
      contexts: ["page", "selection"],
      documentUrlPatterns: ["<all_urls>"]
    });
    api.menus.create({
      id: "forge-stop",
      title: "Stop reading (FORGE)",
      contexts: ["page", "selection"],
      documentUrlPatterns: ["<all_urls>"]
    });
  });
}

buildMenus();
api.runtime.onInstalled.addListener(buildMenus);

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

api.commands.onCommand.addListener(async (name) => {
  const tab = await activeTab();
  if (!tab || !tab.id) return;
  if (name === "read-selection" || name === "read-page") {
    tell(tab.id, { forge: "speak", from: name === "read-selection" ? "selection" : "page", maxChars: PARAGRAPH });
  } else if (name === "stop") {
    tell(tab.id, { forge: "stop" });
  } else if (name === "toggle") {
    tell(tab.id, { forge: "toggle" });
  }
});

api.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || msg.forge !== "from-page") return;
  if (msg.what === "status") {
    api.browserAction.setBadgeText({ text: msg.badge || "" });
    api.browserAction.setBadgeBackgroundColor({ color: msg.error ? "#c0392b" : "#e8b04b" });
  }
});
