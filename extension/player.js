/* FORGE — page-side player.
 *
 * Runs in every page. Turns "read this page / this selection" into a sequence
 * of short requests to your local FORGE server, and plays them back to back.
 * Short requests matter: a 40 000-word page in one request would sit silent
 * for ten minutes and look broken.
 *
 * Speech playback happens in this tab, by the page's own <audio> element, so
 * Firefox's autoplay policy stays satisfied after the first user gesture. */
(function () {
  "use strict";
  if (window.__forgeReader) return;          // one per page
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
  var idx = 0;
  var playing = false;
  var gen = 0;

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
    var t = settings.token ? (path.indexOf("?") > -1 ? "&" : "?") + "token=" + encodeURIComponent(settings.token) : "";
    return base + path + t;
  }

  /* ---------------- text extraction ---------------- */

  function textOf(el) {
    // innerText is what Firefox renders (skips hidden bits); textContent is
    // the fallback for odd documents and for tests.
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
    return text.split(/\n{2,}/).map(function (t) {
      return { text: t.replace(/\s+/g, " ").trim(), el: block };
    }).filter(function (p) { return p.text.length > 1; });
  }

  /* ---------------- chunking ---------------- */

  function sendStatus(badge, error) {
    try {
      chrome.runtime.sendMessage({ forge: "from-page", what: "status", badge: badge, error: !!error });
    } catch (e) { /* extension context gone after reload */ }
  }

  function chunk(items, maxChars) {
    var out = [];
    items.forEach(function (it) {
      var text = it.text;
      if (text.length <= maxChars) { out.push({ text: text, el: it.el }); return; }
      // Long paragraph: split on sentence ends, then hard-wrap.
      var parts = text.split(/(?<=[.!?…])\s+/);
      var buf = "";
      parts.forEach(function (p) {
        if ((buf + " " + p).length > maxChars && buf) { out.push({ text: buf.trim(), el: it.el }); buf = ""; }
        if (p.length > maxChars) {
          for (var i = 0; i < p.length; i += maxChars) out.push({ text: p.substr(i, maxChars), el: it.el });
        } else {
          buf += (buf ? " " : "") + p;
        }
      });
      if (buf.trim()) out.push({ text: buf.trim(), el: it.el });
    });
    return out;
  }

  /* ---------------- playback ---------------- */

  function speakChunk(i, myGen) {
    if (myGen !== gen) return;
    if (i >= queue.length) {
      stop("done");
      return;
    }
    var item = queue[i];
    if (settings.autoScroll && item.el && item.el.scrollIntoView) {
      try { item.el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {}
    }
    sendStatus(Math.round(100 * i / queue.length) + "%");

    fetch(serverURL("/speak"), {
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
          throw new Error(msg.slice(0, 300));
        });
      }
      return r.blob();
    }).then(function (blob) {
      if (myGen !== gen) return;
      audio.src = URL.createObjectURL(blob);
      audio.onended = function () {
        URL.revokeObjectURL(audio.src);
        if (playing) speakChunk(i + 1, myGen);
      };
      return audio.play();
    }).catch(function (e) {
      if (String(e.name) === "AbortError") return;
      console.warn("[FORGE]", e);
      sendStatus("!", true);
      stop("error", e.message || String(e));
    });
  }

  function start(items, maxChars) {
    stop("restart");
    loadSettings().then(function () {
      queue = chunk(items, Math.max(200, Math.min(maxChars || 900, 4500)));
      if (!queue.length) return;
      idx = 0;
      playing = true;
      gen++;
      speakChunk(0, gen);
    });
  }

  function stop(why, detail) {
    gen++;
    playing = false;
    audio.onended = null;
    try { audio.pause(); } catch (e) {}
    if (audio.src) { URL.revokeObjectURL(audio.src); audio.removeAttribute("src"); }
    sendStatus("", why === "error");
    if (why === "error") {
      console.error("[FORGE] " + (detail || "failed") + "\nIs `python -m forge.server` running?");
    }
  }

  /* ---------------- messages ---------------- */

  chrome.runtime.onMessage.addListener(function (msg, sender, reply) {
    if (!msg || !msg.forge) return;
    if (msg.forge === "stop") { stop("stopped"); return; }
    if (msg.forge === "speak") {
      var items;
      if (msg.from === "selection") {
        items = msg.text ? msg.text.split(/\n{2,}/).map(function (t) {
          return { text: t.replace(/\s+/g, " ").trim(), el: null };
        }) : selectionParagraphs();
        if (!items.length) items = selectionParagraphs();
        if (!items.length) items = paragraphsFrom(bestArticle());
      } else {
        items = paragraphsFrom(bestArticle());
      }
      start(items, msg.maxChars);
    }
  });
})();
