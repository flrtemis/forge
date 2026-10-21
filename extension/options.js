/* FORGE — extension settings. */
"use strict";
const api = typeof browser !== "undefined" ? browser : chrome;

const DEFAULTS = {
  server: "http://127.0.0.1:5004", token: "", lang: "en",
  speed: 1.0, temperature: 0.7, autoScroll: true, readCode: false
};

function $(id) { return document.getElementById(id); }

function say(msg, bad) {
  $("status").textContent = msg;
  $("status").className = "status" + (bad ? " error" : "");
}

function load() {
  api.storage.local.get(DEFAULTS, (s) => {
    $("server").value = s.server;
    $("token").value = s.token;
    $("lang").value = s.lang;
    $("speed").value = s.speed;
    $("temperature").value = s.temperature;
    $("autoScroll").checked = !!s.autoScroll;
    $("readCode").checked = !!s.readCode;
  });
}

function current() {
  return {
    server: ($("server").value || DEFAULTS.server).trim().replace(/\/+$/, ""),
    token: $("token").value.trim(),
    lang: ($("lang").value || "en").trim(),
    speed: Number($("speed").value) || 1.0,
    temperature: Number($("temperature").value) || 0.7,
    autoScroll: $("autoScroll").checked,
    readCode: $("readCode").checked
  };
}

function test() {
  const s = current();
  const url = s.server + "/health" + (s.token ? "?token=" + encodeURIComponent(s.token) : "");
  say("checking " + s.server + " …");
  fetch(url).then((r) => r.json()).then((j) => {
    if (!j.ok) throw new Error(j.error || "not ok");
    say(j.voice
      ? "Connected. Voice: " + (j.name || j.voice) + (j.loaded ? " (loaded on GPU)" : " (loads on first line)")
      : "Server up, but no voice set — restart it with --voice <folder>.");
  }).catch((e) => say("Cannot reach the server: " + e.message, true));
}

document.addEventListener("DOMContentLoaded", () => {
  load();
  $("save").addEventListener("click", () => {
    api.storage.local.set(current(), () => say("Saved."));
  });
  $("test").addEventListener("click", test);
  $("open").addEventListener("click", () => {
    const s = current();
    const url = s.server + "/reader" + (s.token ? "?token=" + encodeURIComponent(s.token) : "");
    api.tabs.create({ url });
  });
});
