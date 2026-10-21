/* FORGE — page-side player.
 *
 * Runs in every page. Three ways in, all from the right-click menu:
 *
 *   Read Aloud                 selected text (or the block under the cursor)
 *   Read Aloud — from here     the clicked paragraph through the end of the article
 *   Read Aloud — whole page    the article body: README, post, doc page
 *
 * Then it speaks, in your own voice, via a server on 127.0.0.1.
 *
 * Three details make this work in practice:
 *
 *  1. Content detection. "The page" is not document.body — it's the README on
 *     GitHub, the post on a blog, the prose on a docs site. CONTENT_SELECTORS
 *     is ordered most-specific-first so `.markdown-body` wins over `<main>`,
 *     which on GitHub would drag in the file list and the sidebar.
 *
 *  2. Short requests. A 40 000-word page in one request would sit silent for
 *     ten minutes and look broken. Chunks are ≤ ~900 characters and prefetched
 *     two ahead, so speech starts almost immediately and never gaps.
 *
 *  3. A gesture fallback. A right-click comes from browser chrome, and
 *     Firefox's autoplay policy does not always count that as a page gesture —
 *     audio.play() can reject and stay silent. When that happens we show a
 *     small "▶ Start reading" bar; one click in the page is a real gesture.
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
    autoScroll: true,
    readCode: false          // code fences inside an article are skipped;
                             // a dedicated code view (GitHub blob) is always read
  };

  /* Most specific first. The first selector that matches something with real
   * prose wins, so a GitHub README (`.markdown-body`) is preferred over the
   * surrounding `<main>`, and a blog post (`article`) over the whole body. */
  var CONTENT_SELECTORS = [
    // 1. Rendered markdown: GitHub repos/issues/PRs, wikis, many docs sites.
    "[data-testid=readme]",
    ".markdown-body",        // before #readme: GitHub wraps the README in a
    "article.markdown-body", // cardboard box with Edit/Preview/Blame buttons
    "#readme",
    ".readme",
    // 2. Named prose containers. These come BEFORE <main>/[role=main] on
    //    purpose: docs sites put the whole sidebar menu inside <main>, and a
    //    blog's <main> often wraps comments and newsletter boxes too.
    ".entry-content",
    ".post-content",
    ".article-body",
    ".md-content",          // mkdocs / material
    ".rst-content",         // sphinx
    ".prose",               // tailwind typography
    ".post",
    // 3. Semantic landmarks, as a last structured resort.
    "article",
    "[role=main]",
    "main"
  ];

  var BLOCK_SELECTOR = [
    "p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "dd", "dt", "figcaption",
    "td.blob-code", ".react-code-line"          // github code views
  ].join(", ");

  var MAX_NODES = 6000;      // sanity cap for enormous pages
  var MIN_ROOT_CHARS = 80;   // a "content root" needs at least this much text
                             // (short docs pages are ~140 chars; 200 missed them)

  var settings = Object.assign({}, DEFAULT_SETTINGS);
  var audio = new Audio();
  audio.preload = "auto";

  var queue = [];        // [{text, el}]
  var idx = 0;           // chunk currently spoken
  var playing = false;   // a session is active (may be paused/gated)
  var paused = false;
  var gated = false;     // waiting for a click because autoplay was blocked
  var gen = 0;           // bumped on every stop/restart; stale work is dropped
  var sessionURL = null; // SPA guard: if the page changes, stop talking

  var lastContext = null;   // {el, url, at} recorded when the menu was opened

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
    if (!el || !el.getBoundingClientRect) return false;
    var style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  var CHROME_SELECTOR = [
    "header", "nav", "footer", "aside",
    "[role=navigation]", "[role=banner]", "[role=contentinfo]", "[role=complementary]",
    "[aria-hidden=true]"
  ].join(", ");

  /* Skip anything inside a header/nav/footer/aside, or an element whose
   * class/id smells like chrome (site-footer, cookie-banner, sidebar,
   * breadcrumbs, file-navigation…). Without this, a body-fallback page read its
   * own "Advertise with us" footer, and GitHub's code view read the toolbar
   * ("Go to file", "Code"). The walk stops at the content root, so a root is
   * never disqualified by its own class. */
  function isChrome(el, stopAt) {
    var node = el;
    while (node && node !== stopAt && node.nodeType === 1) {
      if (node.matches && node.matches(CHROME_SELECTOR)) return true;
      var tag = (node.getAttribute && (node.getAttribute("class") || "") + " " +
                 (node.getAttribute("id") || "")) || "";
      if (/(^|[\s_-])(footer|sidebar|cookie|consent|breadcrumb|nav|navbar|navigation|site-nav|menu|banner|promo|advert|newsletter|subscribe|social|share|toolbar|buttons?)([\s_-]|$)/i.test(tag)) {
        return true;
      }
      node = node.parentElement;
    }
    return false;
  }

  function dropNested(els) {
    // <li><p>…</p></li> and <article><div class="markdown-body">… produce
    // overlapping candidates; keep the outer one so nothing is read twice.
    return els.filter(function (el) {
      return !els.some(function (other) {
        return other !== el && other.contains(el);
      });
    });
  }

  /* Content root(s): the element(s) that actually hold the prose.
   * Returns an array — a page can have several (e.g. an issue with comments). */
  function contentRoots() {
    for (var s = 0; s < CONTENT_SELECTORS.length; s++) {
      var found = [].slice.call(document.querySelectorAll(CONTENT_SELECTORS[s]))
        .filter(function (el) {
          return visible(el) && textOf(el).length >= MIN_ROOT_CHARS;
        });
      if (found.length) {
        found = dropNested(found);
        // Several separate articles (comments, chapters): keep them all, in
        // document order. A single big container: that's the one.
        found.sort(function (a, b) {
          return (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1;
        });
        return found.slice(0, 50);
      }
    }
    return [document.body];
  }

  var CODE_VIEW = "td.blob-code, .react-code-line, .blob-code-inner";

  /* A code fence inside prose: <pre>pip install -r requirements.txt</pre>.
   * Those read badly aloud, so they're skipped unless the user opted in.
   * A dedicated code *view* (GitHub blob page) is not a fence — it's the page. */
  function isCodeFence(el) {
    if (el.matches && el.matches(CODE_VIEW)) return false;
    return el.tagName === "PRE" || !!(el.closest && el.closest("pre"));
  }

  function blocksIn(root) {
    var nodes;
    if (Array.isArray(root)) {
      nodes = root.reduce(function (acc, r) { return acc.concat(blocksIn(r)); }, []);
      return nodes;
    }
    nodes = [].slice.call(root.querySelectorAll(BLOCK_SELECTOR));
    if (!nodes.length) nodes = root === document.body ? [] : [root];
    if (nodes.length > MAX_NODES) nodes = nodes.slice(0, MAX_NODES);
    nodes = dropNested(nodes);

    var out = [];
    var seen = {};
    nodes.forEach(function (el) {
      if (!visible(el)) return;
      if (isChrome(el, root)) return;
      if (!settings.readCode && isCodeFence(el)) return;
      var t = textOf(el);
      if (t.length < 2) return;
      if (/^(accept|reject|allow all|manage cookies|sign in|subscribe|skip to content)/i.test(t) && t.length < 80) return;
      if (seen[t]) return;                       // duplicated markup
      seen[t] = true;
      out.push({ text: t, el: el });
    });
    return out;
  }

  function wholePageItems() {
    return blocksIn(contentRoots());
  }

  function selectionItems() {
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

  function blockFor(node) {
    var el = node && node.nodeType === 1 ? node : (node && node.parentElement);
    if (!el || !el.closest) return null;
    return el.closest(BLOCK_SELECTOR) || null;
  }

  /* "From here": the clicked block, then everything after it in that article.
   * Falls back to the whole page if the click landed outside the content. */
  function fromHereItems(anchor) {
    var block = blockFor(anchor);
    if (!block) return wholePageItems();

    var roots = contentRoots();
    var root = roots.filter(function (r) { return r.contains(block); })[0];
    if (!root) return wholePageItems();          // clicked the nav/sidebar

    var all = blocksIn(root);
    var start = -1;
    for (var i = 0; i < all.length; i++) {
      if (all[i].el === block || all[i].el.contains(block) || block.contains(all[i].el)) {
        start = i;
        break;
      }
    }
    if (start < 0) start = 0;

    var rest = all.slice(start);
    // continue into any later articles on the page (issue comments, etc.)
    var after = roots.slice(roots.indexOf(root) + 1);
    after.forEach(function (r) { rest = rest.concat(blocksIn(r)); });
    return rest.length ? rest : wholePageItems();
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

  /* ---------------- floating UI (shadow DOM, page-proof) ---------------- */

  var ui = { host: null, root: null, label: null, toggle: null, stop: null, dot: null };

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
      if (gated) { startPlayback(); return; }        // a real page gesture
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
    if (!ui.host || !playing) return;
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
    // Single-page apps (GitHub, YouTube, most modern sites) swap the DOM
    // without a reload — reading the old article over the new page is worse
    // than stopping.
    if (sessionURL && location.href !== sessionURL) {
      stop("page changed");
      showUI("Page changed — stopped.");
      setTimeout(function () { if (!playing) hideUI(); }, 2500);
      return;
    }
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
    dropPrefetched();
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
      sessionURL = location.href;
      gen++;
      playChunk(0, gen);
    });
  }

  /* ---------------- remember what was right-clicked ---------------- */

  document.addEventListener("contextmenu", function (e) {
    lastContext = { el: e.target, url: location.href, at: Date.now() };
  }, true);
  document.addEventListener("mousedown", function (e) {
    if (e.button === 2) lastContext = { el: e.target, url: location.href, at: Date.now() };
  }, true);

  function anchorFromContext() {
    if (!lastContext) return null;
    if (lastContext.url !== location.href) return null;      // navigated since
    if (Date.now() - lastContext.at > 120000) return null;   // stale
    return lastContext.el;
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
      // Settings first: readCode decides whether code fences are included.
      loadSettings().then(function () { speakNow(msg); });
    }
  });

  function speakNow(msg) {
    var items = [];
    if (msg.from === "selection") {
      if (msg.text) {
        items = msg.text.split(/\n+/).map(function (t) {
          return { text: t.replace(/\s+/g, " ").trim(), el: null };
        }).filter(function (p) { return p.text.length > 1; });
      }
      if (!items.length) items = selectionItems();
      // Right-clicked with a selection but it vanished? Fall back to where
      // the cursor was, then to the whole page.
      if (!items.length) items = fromHereItems(anchorFromContext());
    } else if (msg.from === "here") {
      items = fromHereItems(anchorFromContext());
    } else {
      items = wholePageItems();
    }
    start(items, msg.maxChars);
  }

  /* Escape stops reading (only when the page itself has focus). */
  window.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && playing) { stop("stopped"); }
  }, true);

  /* SPA navigation: stop as soon as the URL changes. */
  ["popstate", "turbo:load", "pjax:end", "yt-navigate-finish"].forEach(function (ev) {
    window.addEventListener(ev, function () {
      if (playing) {
        stop("page changed");
        showUI("Page changed — stopped.");
        setTimeout(function () { if (!playing) hideUI(); }, 2000);
      }
    });
  });
})();
