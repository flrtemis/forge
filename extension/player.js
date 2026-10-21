/* FORGE — page-side player.
 *
 * Runs in every page. Turns "Read Aloud" on a selection (or the whole page)
 * into a sequence of short requests to your local FORGE server, and plays the
 * answers back to back, in your own voice.
 *
 * Two things make this work in practice:
 *
 *  1. Short requests. A 40 000-word page in one request would sit silent for
 *     ten minutes and look broken. Chunks are ≤ ~900 characters and prefetched
 *     one ahead, so speech starts almost immediately and never gaps.
 *
 *  2. A gesture fallback. A right-click comes from browser chrome, and
 *     Firefox's autoplay policy does not always count that as a page gesture —
 *     audio.play() can reject with NotAllowedError and stay silent. When that
 *     happens we show a small "▶ Start reading" bar; one click in the page is
 *     a real gesture and playback proceeds normally.
 */
(function () {
  "use strict";
  if (window.__forgeReader) return;          // one player per page
  window.__forgeReader = true;

  var DEFAULT_SETTINGS = {
    server: "http://127.0.0.1:5004",
    token: "",
    lang: "en",
    speed: 1.0,
    temperature: 0.7,
    autoScroll: true
  };

  var settings = Object.assign({}, DEFAULT_SETTINGS);
  var audio = new Audio();
  audio.preload = "auto";

  var queue = [];        // [{text, el}]
  var idx = 0;           // chunk currently spoken
  var playing = false;   // a session is active (may be paused/gated)
  var paused = false;
  var gated = false;     // waiting for a click because autoplay was blocked
  var gen = 0;           // bumped on every stop/restart; stale fetches are dropped

  /* ---------------- settings ---------------- */

  function loadSettings() {
    return new Promise(function (resolve) {
      try {
        chrome.storage.local.get(DEFAULT_SETTINGS, function (got) {
          settings = Object.assign({}, DEFAULT_SETTINGS, got || {});
          resolve(settings);
        });
      } catch (e) {
        resolve(settings);
      }
    });
  }

  function serverURL(path) {
    var base = (settings.server || DEFAULT_SETTINGS.server).replace(/\/+$/, "");
    var t = settings.token
      ? (path.indexOf("?") > -1 ? "&" : "?") + "token=" + encodeURIComponent(settings.token)
      : "";
    return base + path + t;
  }

  /* ---------------- text extraction ---------------- */

  function textOf(el) {
    // innerText is what Firefox renders (skips hidden bits); textContent is
    // the fallback for odd documents.
    return ((el.innerText !== undefined ? el.innerText : el.textContent) || "")
      .replace(/\s+/g, " ").trim();
  }

  function visible(el) {
    if (!el) return false;
    var style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function bestArticle() {
    // Prefer a real <article>/<main>, else the densest <p> container.
    var byContainer = [].slice.call(document.querySelectorAll(
      "article, main, [role=main], .post, .article, .entry-content"));
    byContainer = byContainer.filter(function (el) {
      return visible(el) && textOf(el).length > 400;
    });
    if (byContainer.length) {
      byContainer.sort(function (a, b) { return textOf(b).length - textOf(a).length; });
      return byContainer[0];
    }
    var ps = [].slice.call(document.querySelectorAll("p")).filter(visible);
    if (ps.length) return ps;                      // a list, not a container
    return document.body;
  }

  function paragraphsFrom(root) {
    var nodes;
    if (Array.isArray(root)) {
      nodes = root;
    } else {
      nodes = [].slice.call(root.querySelectorAll("p, li, h1, h2, h3, blockquote, pre"));
      if (!nodes.length) nodes = [root];
    }
    var out = [];
    nodes.forEach(function (el) {
      if (!visible(el)) return;
      var t = textOf(el);
      if (t.length < 2) return;
      if (/^(accept|reject|allow all|manage cookies|sign in|subscribe)/i.test(t) && t.length < 80) return;
      out.push({ text: t, el: el });
    });
    return out;
  }

  function selectionParagraphs() {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) return [];
    var text = sel.toString().trim();
    if (!text) return [];
    var node = sel.anchorNode;
    var block = node && (node.nodeType === 1 ? node : node.parentElement);
    return text.split(/\n+/)
      .map(function (t) { return t.replace(/\s+/g, " ").trim(); })
      .filter(function (t) { return t.length > 1; })
      .map(function (t) { return { text: t, el: block }; });
  }

  /* ---------------- chunking ---------------- */

  function chunk(items, maxChars) {
    var out = [];
    items.forEach(function (it) {
      var text = (it.text || "").trim();
      if (!text) return;
      if (text.length <= maxChars) { out.push({ text: text, el: it.el }); return; }
      // Long paragraph: split on sentence ends, then hard-wrap the stragglers.
      var parts = text.split(/(?<=[.!?…])\s+/);
      var buf = "";
      parts.forEach(function (p) {
        if (p.length > maxChars) {
          if (buf) { out.push({ text: buf.trim(), el: it.el }); buf = ""; }
          for (var i = 0; i < p.length; i += maxChars) {
            out.push({ text: p.substr(i, maxChars).trim(), el: it.el });
          }
          return;
        }
        if (buf && (buf.length + 1 + p.length) > maxChars) {
          out.push({ text: buf.trim(), el: it.el });
          buf = "";
        }
        buf += (buf ? " " : "") + p;
      });
      if (buf.trim()) out.push({ text: buf.trim(), el: it.el });
    });
    return out;
  }

  /* ---------------- tiny floating UI (shadow DOM, page-proof) --------- */

  var ui = { host: null, root: null, label: null, toggle: null, stop: null };

  function ensureUI() {
    if (ui.host) return;
    var host = document.createElement("div");
    host.id = "__forge_player";
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;";
    var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;

    var style = document.createElement("style");
    style.textContent = [
      ":host{all:initial}",
      ".bar{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:10px;",
      "background:#1b1e24;color:#e7e4dd;border:1px solid #2a2e36;",
      "box-shadow:0 6px 24px rgba(0,0,0,.35);font:13px/1.3 'Segoe UI',system-ui,sans-serif;",
      "max-width:340px}",
      ".dot{width:8px;height:8px;border-radius:50%;background:#e8b04b;flex:0 0 auto}",
      ".dot.idle{background:#5fbf8a}",
      ".label{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px}",
      "button{all:unset;cursor:pointer;padding:4px 9px;border-radius:6px;border:1px solid #2a2e36;",
      "background:#14161a;color:#e7e4dd;font:inherit}",
      "button:hover{border-color:#e8b04b}",
      "button.main{background:#e8b04b;border-color:#e8b04b;color:#1a1610;font-weight:600}"
    ].join("");

    var bar = document.createElement("div");
    bar.className = "bar";

    var dot = document.createElement("span");
    dot.className = "dot";

    var label = document.createElement("span");
    label.className = "label";
    label.textContent = "FORGE";

    var toggleBtn = document.createElement("button");
    toggleBtn.className = "main";
    toggleBtn.textContent = "▶";
    toggleBtn.title = "Play / pause";

    var stopBtn = document.createElement("button");
    stopBtn.textContent = "■";
    stopBtn.title = "Stop reading";

    bar.appendChild(dot);
    bar.appendChild(label);
    bar.appendChild(toggleBtn);
    bar.appendChild(stopBtn);
    root.appendChild(style);
    root.appendChild(bar);
    document.documentElement.appendChild(host);

    ui.host = host;
    ui.root = root;
    ui.label = label;
    ui.toggle = toggleBtn;
    ui.stop = stopBtn;
    ui.dot = dot;

    toggleBtn.addEventListener("click", function () {
      if (gated) { startPlayback(); return; }        // real page gesture
      if (paused) { resume(); } else { pause(); }
    });
    stopBtn.addEventListener("click", function () { stop("stopped"); });
  }

  function showUI(text) {
    ensureUI();
    ui.label.textContent = text;
    ui.host.style.display = "";
  }

  function hideUI() {
    if (ui.host) ui.host.style.display = "none";
  }

  function render() {
    if (!ui.host) return;
    if (!playing) return;
    var total = queue.length;
    var what = total ? " " + Math.min(idx + 1, total) + "/" + total : "";
    if (gated) {
      ui.label.textContent = "Autoplay blocked — click ▶ to start";
      ui.toggle.textContent = "▶ Start";
      ui.dot.className = "dot";
    } else if (paused) {
      ui.label.textContent = "Paused" + what;
      ui.toggle.textContent = "▶";
      ui.dot.className = "dot";
    } else {
      ui.label.textContent = "Reading…" + what;
      ui.toggle.textContent = "❚❚";
      ui.dot.className = "dot idle";
    }
  }

  function sendStatus(badge, error) {
    try {
      chrome.runtime.sendMessage({ forge: "from-page", what: "status", badge: badge, error: !!error });
    } catch (e) { /* extension reloaded mid-session */ }
  }

  /* ---------------- playback ---------------- */

  var prefetched = {};     // index -> object URL, fetched ahead of playback

  function fetchChunk(i, myGen) {
    var item = queue[i];
    if (!item) return Promise.resolve(null);
    return fetch(serverURL("/speak"), {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" },
        settings.token ? { "X-Forge-Token": settings.token } : {}),
      body: JSON.stringify({
        text: item.text,
        lang: settings.lang,
        speed: settings.speed,
        temperature: settings.temperature
      })
    }).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) {
          var msg = t;
          try { msg = JSON.parse(t).error || t; } catch (e) {}
          throw new Error(String(msg).slice(0, 300));
        });
      }
      return r.blob();
    }).then(function (blob) {
      if (myGen !== gen) return null;
      return URL.createObjectURL(blob);
    });
  }

  function prefetch(i, myGen) {
    if (i >= queue.length || prefetched[i]) return;
    prefetched[i] = "pending";
    fetchChunk(i, myGen).then(function (url) {
      if (!url) { delete prefetched[i]; return; }
      if (myGen !== gen) { URL.revokeObjectURL(url); return; }
      prefetched[i] = url;
    }).catch(function () { delete prefetched[i]; /* the real attempt reports it */ });
  }

  // Two chunks ahead: synthesis is slower than playback, so one is not enough
  // to keep a long paragraph from gapping.
  function prefetchAhead(i, myGen) {
    prefetch(i, myGen);
    prefetch(i + 1, myGen);
  }

  function urlFor(i, myGen) {
    var got = prefetched[i];
    if (got && got !== "pending") {
      delete prefetched[i];
      return Promise.resolve(got);
    }
    return fetchChunk(i, myGen);
  }

  function dropPrefetched() {
    Object.keys(prefetched).forEach(function (k) {
      var u = prefetched[k];
      if (u && u !== "pending") URL.revokeObjectURL(u);
    });
    prefetched = {};
  }

  function playChunk(i, myGen) {
    if (myGen !== gen) return;
    if (i >= queue.length) { finish(); return; }
    idx = i;
    var item = queue[i];

    if (settings.autoScroll && item && item.el && item.el.scrollIntoView) {
      try { item.el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {}
    }
    showUI("Reading… " + (i + 1) + "/" + queue.length);
    render();
    sendStatus(Math.round(100 * i / queue.length) + "%");

    urlFor(i, myGen).then(function (url) {
      if (!url || myGen !== gen) return;
      prefetchAhead(i + 1, myGen);
      audio.src = url;
      audio.onended = function () {
        if (myGen !== gen) return;
        playChunk(i + 1, myGen);
      };
      return audio.play().then(function () {
        gated = false;
        render();
      }, function (err) {
        var name = String((err && err.name) || err);
        if (name === "NotAllowedError") {
          // Autoplay policy: keep the audio ready, ask for one click.
          gated = true;
          playing = true;
          render();
          sendStatus("▶", false);
          return;
        }
        throw err;
      });
    }).catch(function (err) {
      if (myGen !== gen) return;
      var msg = String((err && err.message) || err).split("\n")[0];
      showUI("FORGE error: " + msg);
      sendStatus("!", true);
      console.error("[FORGE] " + msg +
        "\nIf this says 'Failed to fetch', the server is not running: " +
        "start it with  python -m forge.server");
      playing = false;
    });
  }

  /* Called from the ▶ button — a genuine page gesture, so play() is allowed. */
  function startPlayback() {
    if (!playing) return;
    gated = false;
    audio.play().then(function () {
      gated = false;
      render();
    }).catch(function (err) {
      showUI("Could not play: " + ((err && err.message) || err));
    });
  }

  function pause() {
    paused = true;
    if (!gated) audio.pause();
    render();
  }

  function resume() {
    paused = false;
    if (gated) { startPlayback(); return; }
    audio.play().catch(function () { gated = true; render(); });
    render();
  }

  function finish() {
    playing = false;
    paused = false;
    gated = false;
    audio.onended = null;
    if (audio.src) { URL.revokeObjectURL(audio.src); audio.removeAttribute("src"); }
    if (ui.label) ui.label.textContent = "Done.";
    sendStatus("");
    setTimeout(function () { if (!playing) hideUI(); }, 2500);
  }

  function stop(why, detail) {
    gen++;
    playing = false;
    paused = false;
    gated = false;
    audio.onended = null;
    try { audio.pause(); } catch (e) {}
    if (audio.src) { URL.revokeObjectURL(audio.src); audio.removeAttribute("src"); }
    dropPrefetched();
    hideUI();
    sendStatus("", why === "error");
    if (why === "error") {
      console.error("[FORGE] " + (detail || "failed") +
        "\nIs `python -m forge.server` running? Start it, then reload this page.");
    }
  }

  function start(items, maxChars) {
    stop("restart");
    loadSettings().then(function () {
      queue = chunk(items, Math.max(200, Math.min(maxChars || 900, 4500)));
      if (!queue.length) {
        showUI("Nothing to read here.");
        setTimeout(function () { if (!playing) hideUI(); }, 2500);
        return;
      }
      idx = 0;
      playing = true;
      paused = false;
      gated = false;
      gen++;
      playChunk(0, gen);
    });
  }

  /* ---------------- messages from background.js ---------------- */

  chrome.runtime.onMessage.addListener(function (msg) {
    if (!msg || !msg.forge) return;
    if (msg.forge === "stop") { stop("stopped"); return; }
    if (msg.forge === "toggle") {
      if (!playing) return;
      if (gated) { startPlayback(); } else if (paused) { resume(); } else { pause(); }
      return;
    }
    if (msg.forge === "speak") {
      var items;
      if (msg.from === "selection") {
        items = msg.text ? msg.text.split(/\n+/).map(function (t) {
          return { text: t.replace(/\s+/g, " ").trim(), el: null };
        }).filter(function (p) { return p.text.length > 1; }) : [];
        if (!items.length) items = selectionParagraphs();
        if (!items.length) items = paragraphsFrom(bestArticle());
      } else {
        items = paragraphsFrom(bestArticle());
      }
      start(items, msg.maxChars);
    }
  });

  /* Escape stops reading (only when the page itself has focus). */
  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && playing) { stop("stopped"); }
  }, true);
})();
